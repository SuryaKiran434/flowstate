// Storage and retrieval of the Flowstate session token.
//
// The token arrives as a `?token=` query parameter on a redirect back from the
// backend's OAuth callback, which means anyone who can get the user to open a
// URL controls its contents. Whatever we persist here is later read back and
// spliced into an `Authorization: Bearer ...` header on every API call, so an
// unvalidated value is both a stored-XSS-shaped hazard and a header-injection
// one (a token carrying CR/LF could smuggle extra headers into a request).
//
// The backend issues a JWT via jose (app/core/security.create_access_token), so
// a legitimate token is always three base64url segments joined by dots. We check
// that shape before writing, and again after reading, so a value planted in
// localStorage by other means cannot reach a request header either.

export const TOKEN_STORAGE_KEY = 'flowstate_token'

// Three non-empty base64url segments. Deliberately no padding: JWT segments are
// unpadded base64url by RFC 7515.
const JWT_RE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/
const MAX_TOKEN_LENGTH = 4096

export function isValidSessionToken(raw) {
  return (
    typeof raw === 'string' &&
    raw.length > 0 &&
    raw.length <= MAX_TOKEN_LENGTH &&
    JWT_RE.test(raw)
  )
}

/**
 * Return the token if it is a well-formed JWT, otherwise null. No side effects.
 */
export function sanitizeSessionToken(raw) {
  if (!isValidSessionToken(raw)) return null
  // Taken from the match so the value we hand back is the validated one.
  return JWT_RE.exec(raw)[0]
}

/**
 * Persist a session token if — and only if — it is a well-formed JWT.
 * Returns the stored token, or null when the candidate was rejected.
 */
export function storeSessionToken(raw) {
  const token = sanitizeSessionToken(raw)
  if (token === null) return null
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
  return token
}

/**
 * Read the session token back, dropping (and clearing) anything malformed.
 */
export function readSessionToken() {
  const raw = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (raw === null) return null
  const token = sanitizeSessionToken(raw)
  if (token === null) localStorage.removeItem(TOKEN_STORAGE_KEY)
  return token
}

export function clearSessionToken() {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}
