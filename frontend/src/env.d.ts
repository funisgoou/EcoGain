/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Mock 模式开关：'true' 时走 src/api/mock.ts 内存实现 */
  readonly VITE_USE_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
