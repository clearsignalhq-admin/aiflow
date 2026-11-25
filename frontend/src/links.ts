/** The app introduction video. Every place that links to it reads from here (a test checks the written guide agrees). */
export const INTRO_VIDEO = {
  id: 'aPY--8am13w',
  /** Used for the player's accessible title; the on-page name is "App introduction". */
  title: 'AiFlow introduction video (Idea to Code)',
  watchUrl: 'https://youtu.be/aPY--8am13w',
  /** The privacy-friendly embed address: no cookies are set until the viewer plays the video. */
  embedUrl: 'https://www.youtube-nocookie.com/embed/aPY--8am13w',
} as const;

/** True for the ordinary forms of a YouTube video address; used to keep the stored link honest. */
export function isYouTubeWatchUrl(url: string): boolean {
  return /^https:\/\/(youtu\.be\/|www\.youtube\.com\/watch\?v=)[A-Za-z0-9_-]{11}$/.test(url);
}
