# RAGFlow PDF上传链路性能优化方案

## 1. PDF上传API流程

```
客户端请求 → Quart中间件 → /documents/upload API
                                   ↓
                           FileService.upload_info()
                                   ↓
                    ┌──────────────┴──────────────┐
                    ↓                              ↓
              URL下载                         文件上传
              (AsyncWebCrawler)                file.read()
                    ↓                              ↓
            read_potential_broken_pdf()    read_potential_broken_pdf()
                    ↓                              ↓
              put_blob()                      put_blob()
              (MinIO存储)                     (MinIO存储)
                    ↓                              ↓
              返回元数据                      返回元数据
```

## 2. 发现的性能瓶颈

### 2.1 关键配置参数

| 参数 | 当前值 | 文件位置 | 说明 |
|-----|-------|---------|------|
| `MAX_CONTENT_LENGTH` | 1GB | `api/apps/__init__.py` | 请求体大小限制 |
| `QUART_RESPONSE_TIMEOUT` | 600秒 | `api/apps/__init__.py` | 响应超时 |
| `QUART_BODY_TIMEOUT` | 600秒 | `api/apps/__init__.py` | 请求体超时 |
| `MAX_CONCURRENT_MINIO` | 10 | `task_executor.py` | MinIO并发写入 |

### 2.2 瓶颈分析

#### 瓶颈1: PDF预检验延迟
```python
# file_service.py: upload_info() → structured()
if filetype == FileType.PDF.value:
    blob = read_potential_broken_pdf(blob)  # 额外PDF验证
```
**影响**: 上传后额外进行一次PDF可读性验证，增加延迟

#### 瓶颈2: 串行文件处理
```python
# document_api.py: upload_info()
results = [await thread_pool_exec(FileService.upload_info, tenant_id, f, None) for f in file_objs]
```
**影响**: 多文件上传时串行处理，总时间 = sum(各文件时间)

#### 瓶颈3: MinIO写入无并发控制
```python
# file_service.py: put_blob()
FileService.put_blob(user_id, location, blob)  # 同步写入
```
**影响**: 大量并发上传时MinIO成为瓶颈

#### 瓶颈4: URL下载使用同步asyncio.run
```python
# file_service.py: upload_info() → URL分支
page = asyncio.run(adownload())  # 阻塞事件循环
```
**影响**: 多个URL下载时无法并发

## 3. 优化方案

### 3.1 环境变量优化 (立即生效)

在 `docker/.env` 中添加:

```bash
# ============ 上传链路优化配置 ============

# MinIO并发写入 (关键!)
MAX_CONCURRENT_MINIO=20

# Quart超时配置
QUART_RESPONSE_TIMEOUT=1200
QUART_BODY_TIMEOUT=1200

# 上传文件大小限制 (根据需求调整)
MAX_CONTENT_LENGTH=2147483648  # 2GB
```

### 3.2 代码级优化建议

#### 优化点1: 并行处理多文件上传

**文件**: `/ragflow/api/apps/restful_apis/document_api.py` (约第90行)

**当前代码**:
```python
results = [await thread_pool_exec(FileService.upload_info, tenant_id, f, None) for f in file_objs]
```

**优化方案**:
```python
# 使用 asyncio.gather 并行上传
import asyncio

results = await asyncio.gather(
    *[thread_pool_exec(FileService.upload_info, tenant_id, f, None) for f in file_objs],
    return_exceptions=True
)
# 处理异常...
```

#### 优化点2: 异步MinIO写入

**文件**: `/ragflow/api/db/services/file_service.py` (约第617行)

**当前代码**:
```python
@staticmethod
def put_blob(user_id, location, blob):
    bname = f"{user_id}-downloads"
    return settings.STORAGE_IMPL.put(bname, location, blob)
```

**优化方案**:
```python
@staticmethod
async def put_blob_async(user_id, location, blob):
    bname = f"{user_id}-downloads"
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, 
        lambda: settings.STORAGE_IMPL.put(bname, location, blob)
    )
```

#### 优化点3: 跳过不必要的PDF预检验

**文件**: `/ragflow/api/db/services/file_service.py` (约第691行)

**当前代码**:
```python
def structured(filename, filetype, blob, content_type):
    if filetype == FileType.PDF.value:
        blob = read_potential_broken_pdf(blob)  # 上传时也检验
```

**优化方案**:
```python
# 添加环境变量控制
SKIP_PDF_PRECHECK = os.environ.get("SKIP_PDF_PRECHECK", "false").lower() == "true"

def structured(filename, filetype, blob, content_type):
    # 上传阶段跳过检验，交给解析阶段处理
    if filetype == FileType.PDF.value and not SKIP_PDF_PRECHECK:
        blob = read_potential_broken_pdf(blob)
```

#### 优化点4: URL下载并发

**文件**: `/ragflow/api/db/services/file_service.py` (约第760行)

**当前代码**:
```python
# 每个URL单独处理，无法并发
for url in urls:
    page = asyncio.run(adownload())
```

**优化方案**:
```python
async def download_multiple(urls):
    tasks = [adownload(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]
```

### 3.3 Docker Compose优化

修改 `docker/docker-compose.yml`:

```yaml
services:
  ragflow:
    environment:
      - MAX_CONCURRENT_MINIO=20
      - QUART_RESPONSE_TIMEOUT=1200
      - QUART_BODY_TIMEOUT=1200
      - MAX_CONTENT_LENGTH=2147483648
```

## 4. 预期优化效果

| 优化项 | 预期提升 | 实施难度 |
|-------|---------|---------|
| 并行文件处理 | 50%+ (多文件) | 中 |
| MinIO并发写入 | 20-30% | 低 |
| 跳过PDF预检验 | 10-20% | 低 |
| URL下载并发 | 60%+ (多URL) | 中 |

## 5. 快速验证

```bash
# 1. 修改 .env 后重启
docker compose down && docker compose up -d

# 2. 测试大文件上传
curl -X POST "http://localhost:9380/api/v1/datasets/{id}/documents/upload" \
  -H "Authorization: Bearer {token}" \
  -F "file=@large_file.pdf"

# 3. 监控上传速度
docker stats docker-ragflow-cpu-1 --no-stream

# 4. 监控MinIO
docker logs docker-minio -f
```

## 6. 注意事项

1. **PDF预检验**: 跳过可能接受损坏PDF，建议在解析时检测
2. **并发数过高**: 可能导致MinIO连接池耗尽，根据服务器配置调整
3. **超时配置**: PDF大文件需要足够长的超时时间

---

*文档生成时间: 2026-06-14*
