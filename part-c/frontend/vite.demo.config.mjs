import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const proxy = {
  '/v1': {
    target: 'https://vec07o9pei.execute-api.us-east-1.amazonaws.com',
    changeOrigin: true,
    secure: true,
    timeout: 45000,
    proxyTimeout: 45000,
  },
};

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  build: { target: 'es2022' },
});
