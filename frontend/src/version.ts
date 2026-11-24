// Stamped at build time by vite.config.ts (version from package.json, which scripts/sync_version.py keeps in step
// with the root VERSION file). The fallbacks only apply where the build step did not run.
declare const __APP_VERSION__: string | undefined;
declare const __APP_COMMIT__: string | undefined;
declare const __APP_BUILD_DATE__: string | undefined;

export const APP_VERSION: string = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0';
export const APP_COMMIT: string = typeof __APP_COMMIT__ !== 'undefined' ? __APP_COMMIT__ : 'unknown';
export const APP_BUILD_DATE: string = typeof __APP_BUILD_DATE__ !== 'undefined' ? __APP_BUILD_DATE__ : 'unknown';
