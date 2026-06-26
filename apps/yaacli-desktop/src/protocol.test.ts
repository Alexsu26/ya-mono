import { describe, expect, test } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import {
  eventEnvelopeSchema,
  handshakeEnvelopeSchema,
  PROTOCOL_VERSION,
  requestEnvelopeSchema,
} from './protocol'

describe('desktop protocol', () => {
  const fixture = (name: string) =>
    JSON.parse(
      readFileSync(
        resolve('../../packages/yaacli/tests/fixtures/desktop_protocol', name),
        'utf8',
      ),
    ) as unknown

  test('accepts a compatible handshake', () => {
    const result = handshakeEnvelopeSchema.parse({
      protocol_version: PROTOCOL_VERSION,
      type: 'handshake',
      runtime_version: '0.1.0',
      capabilities: {
        commands: ['runtime.health'],
        events: ['runtime.health'],
        max_message_bytes: 1024,
        max_attachments: 32,
        steering: true,
        approvals: true,
      },
    })

    expect(result.protocol_version).toBe(PROTOCOL_VERSION)
  })

  test('rejects an incompatible protocol version', () => {
    expect(() =>
      handshakeEnvelopeSchema.parse({
        protocol_version: 2,
        type: 'handshake',
        runtime_version: '0.1.0',
        capabilities: {},
      }),
    ).toThrow()
  })

  test('rejects unknown request fields', () => {
    expect(() =>
      requestEnvelopeSchema.parse({
        protocol_version: PROTOCOL_VERSION,
        type: 'request',
        request_id: 'req-1',
        command: 'runtime.health',
        payload: {},
        unexpected: true,
      }),
    ).toThrow()
  })

  test('rejects negative event sequences', () => {
    expect(() =>
      eventEnvelopeSchema.parse({
        protocol_version: PROTOCOL_VERSION,
        type: 'event',
        event: 'text.delta',
        payload: { delta: 'hello' },
        sequence: -1,
      }),
    ).toThrow()
  })

  test('parses shared golden fixtures', () => {
    expect(handshakeEnvelopeSchema.parse(fixture('handshake.json')).type).toBe(
      'handshake',
    )
    expect(requestEnvelopeSchema.parse(fixture('request.json')).type).toBe(
      'request',
    )
    expect(eventEnvelopeSchema.parse(fixture('event.json')).type).toBe('event')
  })

  test('rejects the shared incompatible-version fixture', () => {
    expect(() =>
      handshakeEnvelopeSchema.parse(fixture('invalid-version.json')),
    ).toThrow()
  })
})
