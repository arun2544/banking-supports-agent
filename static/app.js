(() => {
  const $ = (id) => document.getElementById(id);
  let token = null, sessionId = null;

  function add(role, text, agents) {
    const d = document.createElement("div");
    d.className = "msg " + role;
    d.textContent = text;                       // textContent: never inject model output as HTML
    if (agents && agents.length) {
      const c = document.createElement("div");
      c.className = "chip";
      c.textContent = "via " + agents.join(", ") + " agent" + (agents.length > 1 ? "s" : "");
      d.appendChild(c);
    }
    $("log").appendChild(d);
    $("log").scrollTop = $("log").scrollHeight;
  }

  async function login() {
    $("loginErr").textContent = "";
    const r = await fetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("user").value, password: $("pass").value }) });
    if (!r.ok) { $("loginErr").textContent = r.status === 429 ? "Too many attempts. Wait a minute." : "Invalid credentials"; return; }
    const d = await r.json();
    token = d.access_token;                     // kept in memory only
    $("who").textContent = $("user").value + " · " + d.tier;
    $("login").hidden = true; $("chat").hidden = false;
    add("bot", "Hi! How can I help you today?");
    $("msg").focus();
  }

  async function send() {
    const text = $("msg").value.trim();
    if (!text) return;
    $("msg").value = ""; $("send").disabled = true;
    add("user", text);
    try {
      const r = await fetch("/chat", { method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({ message: text, session_id: sessionId }) });
      if (r.status === 401) { add("bot", "Your session expired. Please reload and sign in again."); return; }
      if (!r.ok) { add("bot", r.status === 429 ? "You're sending messages too fast. Please wait a moment." : "Something went wrong. Please try again."); return; }
      const d = await r.json();
      sessionId = d.session_id;
      add("bot", d.reply, d.agents_called);
      $("cost").textContent = "Session LLM cost so far: $" + d.cost_usd_total.toFixed(4);
    } catch { add("bot", "Network error. Please try again."); }
    finally { $("send").disabled = false; $("msg").focus(); }
  }

  $("loginBtn").addEventListener("click", login);
  $("pass").addEventListener("keydown", (e) => e.key === "Enter" && login());
  $("send").addEventListener("click", send);
  $("msg").addEventListener("keydown", (e) => e.key === "Enter" && send());
})();
