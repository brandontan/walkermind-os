import { useState } from 'react';
import { LandingPage } from './components/LandingPage';
import { LaunchForm } from './components/LaunchForm';
import { StreamPanel } from './components/StreamPanel';
import { streamLaunchPlan } from './lib/streamClient';
import type { LaunchFormInput, StreamEvent } from './lib/types';

const initialForm: LaunchFormInput = {
  productBrief: 'Launch an incident-aware deploy calendar for cloud release teams.',
  audience: 'Engineering managers and release coordinators at SaaS companies.',
  launchDate: new Date().toISOString().slice(0, 10),
  constraints: 'Two sprint window, no new backend infra, legal review required.',
  assets: 'Demo recording, architecture diagram, beta customer quotes.',
};

export function App() {
  const [view, setView] = useState<'landing' | 'planner'>('landing');
  const [form, setForm] = useState<LaunchFormInput>(initialForm);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [output, setOutput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const onSubmit = async () => {
    setLoading(true);
    setEvents([]);
    setOutput('');
    setError('');

    try {
      await streamLaunchPlan(form, (event) => {
        setEvents((current) => [...current, event]);
        if (event.type === 'text_delta') {
          setOutput((current) => current + event.delta);
        }
        if (event.type === 'final_output') {
          setOutput(event.text);
        }
      });
    } catch (streamError) {
      setError(streamError instanceof Error ? streamError.message : 'Unknown stream error');
    } finally {
      setLoading(false);
    }
  };

  if (view === 'landing') {
    return <LandingPage onLaunch={() => setView('planner')} />;
  }

  return (
    <main className="shell">
      <div className="shell-header">
        <button className="shell-back" onClick={() => setView('landing')}>
          ← Back
        </button>
        <h1>Launch Planner</h1>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <div className="grid">
        <LaunchForm form={form} loading={loading} onChange={setForm} onSubmit={onSubmit} />
        <StreamPanel output={output} events={events} />
      </div>
    </main>
  );
}
