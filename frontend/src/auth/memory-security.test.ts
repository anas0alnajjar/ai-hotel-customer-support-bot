import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('browser credential policy', () => {
  it('keeps bearer credentials out of browser persistence APIs', () => {
    const source = readFileSync(new URL('./AuthContext.tsx', import.meta.url), 'utf8')
    expect(source).not.toMatch(/localStorage|sessionStorage|indexedDB/)
    expect(source).toContain('useState')
  })
})
