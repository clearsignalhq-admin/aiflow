import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { INTRO_VIDEO, isYouTubeWatchUrl } from './links';
import { VideoEmbed } from './components/VideoEmbed';
import { Toolbar } from './components/Toolbar';
import LandingPage from './pages/LandingPage';
import GuidePage from './pages/GuidePage';

vi.mock('./hooks/useAnalytics', () => ({ useAnalytics: () => ({ track: vi.fn() }) }));
vi.mock('./context/AuthContext', () => ({
  useAuth: () => ({ user: { email: 'a@b.c' }, profile: { role: 'user', name: 'Ada' }, session: { access_token: 't' }, signOut: vi.fn() }),
}));

describe('the video address', () => {
  it('is consistent: one id, used by the watch and embed addresses', () => {
    expect(INTRO_VIDEO.id).toMatch(/^[A-Za-z0-9_-]{11}$/);
    expect(INTRO_VIDEO.watchUrl).toBe(`https://youtu.be/${INTRO_VIDEO.id}`);
    expect(INTRO_VIDEO.embedUrl).toBe(`https://www.youtube-nocookie.com/embed/${INTRO_VIDEO.id}`);
    expect(isYouTubeWatchUrl(INTRO_VIDEO.watchUrl)).toBe(true);
  });

  it('recognises ordinary YouTube watch addresses and nothing else', () => {
    for (const ok of ['https://youtu.be/aPY--8am13w', 'https://www.youtube.com/watch?v=aPY--8am13w']) expect(isYouTubeWatchUrl(ok)).toBe(true);
    for (const bad of ['', 'http://youtu.be/aPY--8am13w', 'https://youtu.be/short', 'https://evil.example/watch?v=aPY--8am13w', 'javascript:alert(1)', 'https://youtu.be/aPY--8am13w?x=1']) {
      expect(isYouTubeWatchUrl(bad), bad).toBe(false);
    }
  });

  it('is the one the written guide links to', () => {
    const guide = readFileSync(join(__dirname, '..', '..', 'docs', 'user-guide', 'README.md'), 'utf-8');
    expect(guide).toContain(`(${INTRO_VIDEO.watchUrl})`);
    const storyboards = readFileSync(join(__dirname, '..', '..', 'docs', 'video-guide', 'README.md'), 'utf-8');
    expect(storyboards).toContain(INTRO_VIDEO.watchUrl.replace('https://', ''));
  });
});

describe('VideoEmbed', () => {
  const embed = () => render(<VideoEmbed embedUrl={INTRO_VIDEO.embedUrl} watchUrl={INTRO_VIDEO.watchUrl} title={INTRO_VIDEO.title} />);

  it('loads nothing from the video site until it is played', () => {
    const { container } = embed();
    expect(container.querySelector('iframe')).toBeNull();
    expect(screen.getByRole('button', { name: `Play video: ${INTRO_VIDEO.title}` })).toBeInTheDocument();
  });

  it('plays inside the page, from the privacy-friendly address, after a click', () => {
    const { container } = embed();
    fireEvent.click(screen.getByRole('button', { name: /Play video/ }));
    const frame = container.querySelector('iframe')!;
    expect(frame.getAttribute('src')).toBe(`${INTRO_VIDEO.embedUrl}?autoplay=1&rel=0`);
    expect(frame).toHaveAttribute('title', INTRO_VIDEO.title);
    expect(frame.getAttribute('allow')).toContain('autoplay');
    expect(frame.hasAttribute('allowfullscreen')).toBe(true);
    expect(frame).toHaveAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    expect(screen.queryByRole('button', { name: /Play video/ })).toBeNull();
  });

  it('always offers a plain link to watch it on YouTube', () => {
    embed();
    const link = screen.getByRole('link', { name: 'Watch on YouTube' });
    expect(link).toHaveAttribute('href', INTRO_VIDEO.watchUrl);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });
});

describe('landing page video', () => {
  const page = () => render(<MemoryRouter><LandingPage /></MemoryRouter>);

  it('has an introduction section right after the hero, with nothing loaded yet', () => {
    const { container } = page();
    const heading = screen.getByRole('heading', { name: 'Watch the app introduction' });
    const sections = [...container.querySelectorAll('section')];
    expect(sections.indexOf(heading.closest('section')!)).toBe(1);                       // hero is the first section, this the second
    expect(container.querySelector('iframe')).toBeNull();
    expect(within(heading.closest('section')!).getByRole('button', { name: /Play video/ })).toBeInTheDocument();
  });

  it('plays the video when asked, and links to YouTube', () => {
    const { container } = page();
    fireEvent.click(screen.getByRole('button', { name: /Play video/ }));
    expect(container.querySelector('iframe')!.getAttribute('src')).toContain(INTRO_VIDEO.embedUrl);
    expect(screen.getByRole('link', { name: 'Watch on YouTube' })).toHaveAttribute('href', INTRO_VIDEO.watchUrl);
  });
});

describe('Help menu video', () => {
  const base = { workflowName: 'W', onNew: vi.fn(), onSave: vi.fn(), onOpen: vi.fn(), onOpenExamplePicker: vi.fn(), onValidate: vi.fn(), onGenerate: vi.fn(), onRefine: vi.fn(), onSimulate: vi.fn(), onEditJson: vi.fn(), onNameChange: vi.fn() };

  it('opens the video from the Help menu', () => {
    const onVideo = vi.fn();
    render(<MemoryRouter><Toolbar {...base} onVideo={onVideo} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'App introduction video' }));
    expect(onVideo).toHaveBeenCalledOnce();
  });

  it('is unavailable (and says so) when there is no handler, and findable in the action search', () => {
    render(<MemoryRouter><Toolbar {...base} onVideo={vi.fn()} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Search actions' }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'video' } });
    expect(screen.getByRole('option')).toHaveTextContent('App introduction video');
  });
});

describe('the written guide', () => {
  it('shows the video link at the top of the in-app guide, opening in a new tab', () => {
    render(<MemoryRouter initialEntries={['/guide']}><GuidePage /></MemoryRouter>);
    const link = screen.getByRole('link', { name: 'Watch the app introduction video' });
    expect(link).toHaveAttribute('href', INTRO_VIDEO.watchUrl);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
