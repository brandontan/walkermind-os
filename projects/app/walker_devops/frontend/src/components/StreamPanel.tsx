import type { StreamEvent } from '../lib/types';

type StreamPanelProps = {
  output: string;
  events: StreamEvent[];
};

export function StreamPanel({ output, events }: StreamPanelProps) {
  return (
    <section className="panel output-panel">
      <h2>Agent output</h2>
      <div className="output">{output || 'Output will stream here as the agent works.'}</div>
      <h3>Progress events</h3>
      <ul>
        {events.map((event, index) => (
          <li key={`${event.type}-${index}`}>
            {event.type === 'tool_event'
              ? `Tool: ${event.name} (${event.itemType})`
              : event.type === 'text_delta'
                ? `Text delta: ${event.delta.slice(0, 50)}`
                : 'Final output received'}
          </li>
        ))}
      </ul>
    </section>
  );
}
