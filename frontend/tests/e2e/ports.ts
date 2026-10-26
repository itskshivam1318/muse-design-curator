/** Fixed ports for the e2e servers; they differ from `make dev` (8000 / 5173). */
export const API_PORT = 8765
export const SITE_PORT = 8766
export const APP_PORT = 5174
export const API_URL = `http://127.0.0.1:${API_PORT}`
export const SITE_URL = `http://127.0.0.1:${SITE_PORT}`
export const APP_URL = `http://127.0.0.1:${APP_PORT}`
