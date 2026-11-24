import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { JsonField } from './JsonField';

describe('JsonField', () => {
  it('shows the current value pretty-printed', () => {
    render(<JsonField value={{ a: 1 }} onCommit={vi.fn()} ariaLabel="f" />);
    expect((screen.getByLabelText('f') as HTMLTextAreaElement).value).toBe('{\n  "a": 1\n}');
  });

  it('commits valid JSON objects', () => {
    const onCommit = vi.fn();
    render(<JsonField value={undefined} onCommit={onCommit} ariaLabel="f" />);
    fireEvent.change(screen.getByLabelText('f'), { target: { value: '{"tier":"gold"}' } });
    expect(onCommit).toHaveBeenCalledWith({ tier: 'gold' });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('does not commit invalid JSON and shows an error', () => {
    const onCommit = vi.fn();
    render(<JsonField value={undefined} onCommit={onCommit} ariaLabel="f" />);
    fireEvent.change(screen.getByLabelText('f'), { target: { value: '{"tier":' } });
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/invalid json/i);
  });

  it.each(['[1,2]', '"text"', '42', 'null'])('rejects non-object JSON %s', (text) => {
    const onCommit = vi.fn();
    render(<JsonField value={undefined} onCommit={onCommit} ariaLabel="f" />);
    fireEvent.change(screen.getByLabelText('f'), { target: { value: text } });
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/json object/i);
  });

  it('commits undefined when cleared', () => {
    const onCommit = vi.fn();
    render(<JsonField value={{ a: 1 }} onCommit={onCommit} ariaLabel="f" />);
    fireEvent.change(screen.getByLabelText('f'), { target: { value: '  ' } });
    expect(onCommit).toHaveBeenCalledWith(undefined);
  });

  it('adopts external changes (e.g. undo) but keeps the user formatting when equivalent', () => {
    const { rerender } = render(<JsonField value={{ a: 1 }} onCommit={vi.fn()} ariaLabel="f" />);
    fireEvent.change(screen.getByLabelText('f'), { target: { value: '{"a":    1}' } });
    rerender(<JsonField value={{ a: 1 }} onCommit={vi.fn()} ariaLabel="f" />);
    expect((screen.getByLabelText('f') as HTMLTextAreaElement).value).toBe('{"a":    1}');

    rerender(<JsonField value={{ a: 2 }} onCommit={vi.fn()} ariaLabel="f" />);
    expect((screen.getByLabelText('f') as HTMLTextAreaElement).value).toBe('{\n  "a": 2\n}');
  });
});
