import type { LaunchFormInput } from '../lib/types';

type LaunchFormProps = {
  form: LaunchFormInput;
  loading: boolean;
  onChange: (next: LaunchFormInput) => void;
  onSubmit: () => void;
};

export function LaunchForm({ form, loading, onChange, onSubmit }: LaunchFormProps) {
  return (
    <section className="panel form-panel">
      <h2>Launch input</h2>
      <label>
        Product brief
        <textarea
          value={form.productBrief}
          onChange={(event) => onChange({ ...form, productBrief: event.target.value })}
        />
      </label>
      <label>
        Audience
        <input value={form.audience} onChange={(event) => onChange({ ...form, audience: event.target.value })} />
      </label>
      <label>
        Launch date
        <input
          type="date"
          value={form.launchDate}
          onChange={(event) => onChange({ ...form, launchDate: event.target.value })}
        />
      </label>
      <label>
        Constraints
        <textarea
          value={form.constraints}
          onChange={(event) => onChange({ ...form, constraints: event.target.value })}
        />
      </label>
      <label>
        Available assets
        <textarea value={form.assets} onChange={(event) => onChange({ ...form, assets: event.target.value })} />
      </label>
      <button type="button" disabled={loading} onClick={onSubmit}>
        {loading ? 'Planning...' : 'Generate launch plan'}
      </button>
    </section>
  );
}
