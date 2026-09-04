// HTTP Basic credential encoding (Studio auth).
//
// The server legally accepts non-control Unicode passwords, so credentials
// must be UTF-8 encoded before Base64. Browser `btoa()` only accepts
// Latin-1 and throws `InvalidCharacterError` on e.g. `admin:密码`, which
// would lock out a validly configured administrator before any request is
// sent (Review D-1).

export function basicAuthHeader(username: string, password: string): string {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `Basic ${btoa(binary)}`;
}
