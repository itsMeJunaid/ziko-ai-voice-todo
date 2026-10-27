/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ZIKO_API?: string;
  readonly VITE_ZIKO_TOKEN?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
