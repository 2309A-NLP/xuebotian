const apiBase = "/api";

const form = document.querySelector("form[data-page]");
const notice = document.getElementById("auth-notice");
const submitBtn = document.getElementById("submit-btn");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const confirmPasswordInput = document.getElementById("confirm-password");

const pageType = form?.dataset.page || "login";

function showNotice(message, tone = "info") {
  notice.textContent = message;
  notice.className = `inline-notice inline-notice--${tone}`;
}

function getMessageFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const message = params.get("message");

  if (message === "login_required") {
    return {
      tone: "info",
      text: "请先登录后再进入聊天界面。登录成功后会自动跳转。",
    };
  }

  if (message === "expired") {
    return {
      tone: "warning",
      text: "你的登录状态已经失效，请重新输入账号密码后继续。",
    };
  }

  if (message === "logout") {
    return {
      tone: "success",
      text: "你已安全退出登录。如需继续使用，请重新登录。",
    };
  }

  return null;
}

async function request(url, payload) {
  const response = await fetch(`${apiBase}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  if (!response.ok || data.success === false) {
    throw new Error(data.message || "提交失败，请稍后重试。");
  }
  return data;
}

function validateRegisterForm() {
  const username = usernameInput.value.trim();
  const password = passwordInput.value;
  const confirmPassword = confirmPasswordInput.value;

  if (!username) {
    throw new Error("请先填写用户名。");
  }

  if (!password) {
    throw new Error("请先填写密码。");
  }

  if (!confirmPassword) {
    throw new Error("请再次输入确认密码。");
  }

  if (password !== confirmPassword) {
    throw new Error("两次输入的密码不一致，请确认后重新提交。");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const username = usernameInput.value.trim();
  const password = passwordInput.value;

  try {
    if (pageType === "register") {
      validateRegisterForm();
    } else {
      if (!username || !password) {
        throw new Error("请输入完整的用户名和密码后再继续。");
      }
    }

    submitBtn.disabled = true;
    submitBtn.textContent = pageType === "register" ? "注册中..." : "登录中...";
    showNotice(
      pageType === "register"
        ? "正在创建账号并验证信息，请稍候。"
        : "正在验证登录信息，请稍候。",
      "info",
    );

    const payload =
      pageType === "register"
        ? {
            username,
            password,
            confirm_password: confirmPasswordInput.value,
          }
        : {
            username,
            password,
          };

    const endpoint = pageType === "register" ? "/auth/register" : "/auth/login";
    const result = await request(endpoint, payload);

    showNotice(result.message, "success");
    submitBtn.textContent = pageType === "register" ? "注册成功，正在跳转..." : "登录成功，正在跳转...";

    window.setTimeout(() => {
      window.location.href = "/chat";
    }, 700);
  } catch (error) {
    showNotice(error.message || "提交失败，请稍后重试。", "error");
    submitBtn.disabled = false;
    submitBtn.textContent = pageType === "register" ? "注册并自动登录" : "登录并进入聊天";
  }
});

const initialMessage = getMessageFromQuery();
if (initialMessage) {
  showNotice(initialMessage.text, initialMessage.tone);
}
