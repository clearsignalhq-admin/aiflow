import { useState } from 'react';

interface Props {
  /** The address to embed (an embed URL, not a watch URL). */
  embedUrl: string;
  /** Where to watch it on its own site, shown as a fallback link. */
  watchUrl: string;
  /** What the video is, for screen readers and the play button. */
  title: string;
}

/**
 * A video that costs nothing until it is played: the page shows a plain play button, and only a click loads the player
 * from the video site (so opening the page sends no request there and sets no cookies).
 */
export function VideoEmbed({ embedUrl, watchUrl, title }: Props) {
  const [playing, setPlaying] = useState(false);
  return (
    <div className="video-embed">
      <div className="video-frame">
        {playing ? (
          <iframe
            src={`${embedUrl}?autoplay=1&rel=0`}
            title={title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture; web-share"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <button type="button" className="video-play" onClick={() => setPlaying(true)} aria-label={`Play video: ${title}`}>
            <span className="video-play-icon" aria-hidden="true">▶</span>
            <span className="video-play-label">Play the introduction</span>
          </button>
        )}
      </div>
      <a className="video-fallback" href={watchUrl} target="_blank" rel="noopener noreferrer">Watch on YouTube</a>
    </div>
  );
}
