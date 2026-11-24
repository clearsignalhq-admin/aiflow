import { useState } from 'react';

interface Props {
  value: Record<string, unknown> | undefined;
  placeholder?: string;
  /** Called with a parsed object, or undefined when the field is cleared. Invalid JSON is never committed. */
  onCommit: (value: Record<string, unknown> | undefined) => void;
  ariaLabel?: string;
}

function pretty(value: unknown): string {
  return value === undefined ? '' : JSON.stringify(value, null, 2);
}

function sameJson(text: string, value: unknown): boolean {
  if (text.trim() === '') return value === undefined;
  try {
    return JSON.stringify(JSON.parse(text)) === JSON.stringify(value);
  } catch {
    return false;
  }
}

/** Textarea that edits a JSON object, validating as you type. */
export function JsonField({ value, placeholder, onCommit, ariaLabel }: Props) {
  const external = pretty(value);
  const [text, setText] = useState(external);
  const [prevExternal, setPrevExternal] = useState(external);
  const [error, setError] = useState<string | null>(null);

  // Adopt outside changes (undo/redo, loading another workflow) without clobbering the user's own formatting.
  if (external !== prevExternal) {
    setPrevExternal(external);
    if (!sameJson(text, value)) {
      setText(external);
      setError(null);
    }
  }

  const handleChange = (next: string) => {
    setText(next);
    if (next.trim() === '') {
      setError(null);
      onCommit(undefined);
      return;
    }
    try {
      const parsed: unknown = JSON.parse(next);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setError('Must be a JSON object, e.g. { "field": "value" }');
        return;
      }
      setError(null);
      onCommit(parsed as Record<string, unknown>);
    } catch {
      setError('Invalid JSON — not saved yet');
    }
  };

  return (
    <>
      <textarea
        className={`prop-input prop-textarea prop-json${error ? ' prop-json--invalid' : ''}`}
        value={text}
        placeholder={placeholder}
        aria-label={ariaLabel}
        spellCheck={false}
        onChange={(e) => handleChange(e.target.value)}
      />
      {error && <div className="prop-json-error" role="alert">{error}</div>}
    </>
  );
}
