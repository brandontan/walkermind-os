const payload = {
  productBrief: 'Ship a launch planning copilot for release teams.',
  audience: 'Engineering managers',
  launchDate: '2026-05-15',
  constraints: 'No extra headcount; legal approval required.',
  assets: 'One-pager, demo video',
};

async function main(): Promise<void> {
  const response = await fetch('http://localhost:8787/api/launch-plan/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Stream request failed: ${response.status} ${await response.text()}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = '';
  let sawTool = false;
  let sawText = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';

    for (const frame of frames) {
      const dataLine = frame
        .split('\n')
        .find((line) => line.startsWith('data:'));

      if (!dataLine) continue;
      const raw = dataLine.replace(/^data:\s*/, '');
      if (raw === 'end') continue;

      const event = JSON.parse(raw) as { type: string };
      if (event.type === 'tool_event') sawTool = true;
      if (event.type === 'text_delta') sawText = true;

      if (sawTool && sawText) {
        console.log('PASS: received at least one tool_event and one text_delta event.');
        return;
      }
    }
  }

  throw new Error(`Missing required stream events. sawTool=${sawTool}, sawText=${sawText}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
