import type { LaunchFormInput, StreamEvent } from './types';

export async function streamLaunchPlan(
  body: LaunchFormInput,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch('/api/launch-plan/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok || !response.body) {
    const errorText = await response.text();
    throw new Error(errorText || 'Failed to stream launch plan');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';

    for (const chunk of chunks) {
      const line = chunk
        .split('\n')
        .find((entry) => entry.startsWith('data:'));

      if (!line) continue;
      const data = line.replace(/^data:\s*/, '');
      if (data === 'end') continue;

      onEvent(JSON.parse(data) as StreamEvent);
    }
  }
}
