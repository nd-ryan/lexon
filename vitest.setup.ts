import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './src/test/server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))

afterEach(() => {
  server.resetHandlers()
  cleanup()
})

afterAll(() => server.close())
