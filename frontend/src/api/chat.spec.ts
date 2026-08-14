import { afterEach, describe, expect, it, vi } from 'vitest'

import { packageSearchStream } from '@/api/chat'

describe('packageSearchStream', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends every component as a repeated files field and permits an unbound project', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const files = [
      new File(['alpha'], 'alpha.zip', { type: 'application/zip' }),
      new File(['beta'], 'beta.rar', { type: 'application/vnd.rar' }),
      new File(['gamma'], 'gamma.bin', { type: 'application/octet-stream' }),
    ]

    await packageSearchStream({
      message: 'build',
      sessionId: 'package-session',
      projectRepoId: null,
      files,
    })

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const body = init.body as FormData
    expect(body.get('project_repo_id')).toBeNull()
    expect(body.getAll('files')).toEqual(files)
    expect(body.getAll('files').map((entry) => (entry as File).name)).toEqual([
      'alpha.zip',
      'beta.rar',
      'gamma.bin',
    ])
  })

  it('includes a selected project for a pure Configuration Manager turn', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await packageSearchStream({
      message: 'find package 1.0.0',
      sessionId: 'search-session',
      projectRepoId: 42,
    })

    const body = fetchMock.mock.calls[0][1].body as FormData
    expect(body.get('project_repo_id')).toBe('42')
    expect(body.getAll('files')).toEqual([])
  })
})
