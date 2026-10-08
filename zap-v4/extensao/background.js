const SERVER = "http://127.0.0.1:5000";
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.tipo !== "fetch_servidor") return false;
  (async () => {
    try {
      const options = { method: msg.method || "GET", headers: { "Content-Type": "application/json" } };
      if (options.method !== "GET" && msg.payload != null) options.body = JSON.stringify(msg.payload);
      const response = await fetch(`${SERVER}${msg.endpoint || "/"}`, options);
      const body = await response.text();
      let data;
      try { data = body ? JSON.parse(body) : null; } catch { data = body; }
      sendResponse({ ok: response.ok, status: response.status, data });
    } catch (error) {
      sendResponse({ ok: false, status: 0, erro: String(error?.message || error) });
    }
  })();
  return true;
});
