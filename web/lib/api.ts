export async function request(path: string, init?: RequestInit) {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/auth/"))
      window.location.assign("/login");
    throw new Error(body.error || "Request failed. Please try again.");
  }
  return body;
}
