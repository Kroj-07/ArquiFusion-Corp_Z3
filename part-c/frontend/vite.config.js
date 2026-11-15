import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const backend=`http://127.0.0.1:${process.env.AF_BACKEND_PORT||8000}`;
export default defineConfig({plugins:[react()],server:{host:'127.0.0.1',port:5173,strictPort:true,proxy:{'/v1':backend,'/health':backend}},build:{target:'es2022'}});
