const SESSION_KEY = "rag-session-id";

function createId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function getSessionId(): string {
  if (typeof window === "undefined") {
    return createId();
  }
  let sessionId = window.localStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = createId();
    window.localStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

export function setSessionId(sessionId: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_KEY, sessionId);
}

export function resetSessionId(): string {
  const next = createId();
  setSessionId(next);
  return next;
}
