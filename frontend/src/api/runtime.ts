/** Mock 模式开关：VITE_USE_MOCK=true 时 http/WS 全部切换为内存实现 */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
