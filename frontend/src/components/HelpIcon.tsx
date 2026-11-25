import { useState } from 'react';
import { createPortal } from 'react-dom';

interface Props {
  title: string;
  body: string;
  /** Id of a section of the user guide (for example `safety-checks`); adds a "Read more" link to it. */
  guide?: string;
}

export function HelpIcon({ title, body, guide }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        className="help-icon"
        type="button"
        title={`Help: ${title}`}
        aria-label={`Help: ${title}`}
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        onDragStart={(e) => e.preventDefault()}
      >
        ⓘ
      </button>

      {open && createPortal(
        <div
          className="help-overlay"
          onClick={() => setOpen(false)}
          onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
          role="presentation"
        >
          <div
            className="help-dialog"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal
            aria-labelledby="help-dialog-title"
          >
            <div className="help-dialog-header">
              <span id="help-dialog-title" className="help-dialog-title">{title}</span>
              <button className="modal-close" onClick={() => setOpen(false)} type="button">✕</button>
            </div>
            <div className="help-dialog-body">{body}</div>
            {guide && (
              <div className="help-dialog-more">
                <a href={`/guide#${guide}`} target="_blank" rel="noopener noreferrer">Read more in the user guide</a>
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
