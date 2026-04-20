import { describe, expect, it } from 'vitest';
import { extractTasksTool } from '../agent/tools.js';

describe('extractTasksTool', () => {
  it('returns prioritized tasks', async () => {
    const result = await extractTasksTool.execute({
      productBrief: 'Brief',
      audience: 'Audience',
      launchDate: '2026-05-20',
      constraints: 'Legal sign-off',
      assets: 'Deck',
    });

    expect(result.length).toBeGreaterThan(0);
    expect(result[0]?.priority).toBe('P0');
  });
});
