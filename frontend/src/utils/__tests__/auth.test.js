// Tests for the session-token guard.
//
// The token arrives as a `?token=` query parameter, so its contents are
// attacker-controlled, and it is later spliced into an Authorization header.
// These tests pin the two properties that matter: nothing but a well-formed
// JWT is ever stored, and nothing but a well-formed JWT is ever handed back —
// including when something else planted a value in localStorage.

import { beforeEach, describe, expect, it } from 'vitest'

import {
  TOKEN_STORAGE_KEY,
  clearSessionToken,
  isValidSessionToken,
  readSessionToken,
  sanitizeSessionToken,
  storeSessionToken,
} from '../auth'

// A minimal in-memory Storage, so these tests need no DOM environment.
class MemoryStorage {
  constructor() { this.map = new Map() }
  getItem(k) { return this.map.has(k) ? this.map.get(k) : null }
  setItem(k, v) { this.map.set(k, String(v)) }
  removeItem(k) { this.map.delete(k) }
  clear() { this.map.clear() }
}

const VALID = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEifQ.c2lnbmF0dXJl'

beforeEach(() => {
  globalThis.localStorage = new MemoryStorage()
})

describe('isValidSessionToken', () => {
  it('accepts a three-segment base64url JWT', () => {
    expect(isValidSessionToken(VALID)).toBe(true)
  })

  it.each([
    ['empty string', ''],
    ['two segments', 'aaa.bbb'],
    ['four segments', 'aaa.bbb.ccc.ddd'],
    ['empty middle segment', 'aaa..ccc'],
    ['trailing dot', 'aaa.bbb.'],
    ['base64 padding', 'aaa.bbb.cc=='],
    ['a space', 'aaa.bbb.cc c'],
    ['CRLF header injection', 'aaa.bbb.ccc\r\nX-Admin: true'],
    ['bare newline', 'aaa.bbb.ccc\n'],
    ['a script tag', '<script>alert(1)</script>'],
    ['a slash', 'aaa.bbb.cc/c'],
    ['a plus', 'aaa.bbb.cc+c'],
  ])('rejects %s', (_label, value) => {
    expect(isValidSessionToken(value)).toBe(false)
  })

  it.each([[null], [undefined], [42], [{}], [[]], [true]])(
    'rejects the non-string %s', (value) => {
      expect(isValidSessionToken(value)).toBe(false)
    },
  )

  it('rejects a token longer than 4096 characters', () => {
    const huge = `${'a'.repeat(4096)}.bbb.ccc`
    expect(isValidSessionToken(huge)).toBe(false)
  })

  it('accepts a token exactly at the 4096 limit', () => {
    const exact = `${'a'.repeat(4096 - 'bbb.ccc'.length - 1)}.bbb.ccc`
    expect(exact).toHaveLength(4096)
    expect(isValidSessionToken(exact)).toBe(true)
  })
})

describe('sanitizeSessionToken', () => {
  it('returns the token unchanged when valid', () => {
    expect(sanitizeSessionToken(VALID)).toBe(VALID)
  })

  it('returns null when invalid', () => {
    expect(sanitizeSessionToken('nope')).toBeNull()
  })

  it('has no side effect on storage', () => {
    sanitizeSessionToken(VALID)
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })
})

describe('storeSessionToken', () => {
  it('persists a valid token and returns it', () => {
    expect(storeSessionToken(VALID)).toBe(VALID)
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe(VALID)
  })

  it('stores nothing when the candidate is rejected', () => {
    expect(storeSessionToken('aaa.bbb.ccc\r\nX-Admin: true')).toBeNull()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('leaves an existing good token in place when a bad one is offered', () => {
    storeSessionToken(VALID)
    storeSessionToken('garbage')
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe(VALID)
  })
})

describe('readSessionToken', () => {
  it('returns null when nothing is stored', () => {
    expect(readSessionToken()).toBeNull()
  })

  it('returns a previously stored token', () => {
    storeSessionToken(VALID)
    expect(readSessionToken()).toBe(VALID)
  })

  it('returns null for a value planted by other means', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'aaa.bbb.ccc\r\nX-Admin: true')
    expect(readSessionToken()).toBeNull()
  })

  it('clears a malformed stored value so it is not read twice', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'not-a-jwt')
    readSessionToken()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('leaves a valid stored value in place', () => {
    storeSessionToken(VALID)
    readSessionToken()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe(VALID)
  })
})

describe('clearSessionToken', () => {
  it('removes the stored token', () => {
    storeSessionToken(VALID)
    clearSessionToken()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('is a no-op when nothing is stored', () => {
    expect(() => clearSessionToken()).not.toThrow()
  })
})
