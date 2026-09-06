/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APIX_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
