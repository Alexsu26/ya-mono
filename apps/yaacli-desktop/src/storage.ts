type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'clear'>

const memory = new Map<string, string>()

const memoryStorage: StorageLike = {
  getItem: (key) => memory.get(key) ?? null,
  setItem: (key, value) => memory.set(key, value),
  removeItem: (key) => memory.delete(key),
  clear: () => memory.clear(),
}

function resolveStorage(): StorageLike {
  try {
    if (
      typeof window !== 'undefined' &&
      typeof window.localStorage?.getItem === 'function' &&
      typeof window.localStorage?.setItem === 'function'
    ) {
      return window.localStorage
    }
  } catch {
    // Sandboxed previews and tests can deny localStorage access.
  }
  return memoryStorage
}

export const desktopStorage = resolveStorage()
