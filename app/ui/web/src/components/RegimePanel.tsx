import type { Brief } from "../types";

interface Props {
  brief: Brief;
}

export function RegimePanel({ brief }: Props) {
  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Persona weights this run</h2>
        <span className="section-count">
          confidence {brief.regime.confidence.toFixed(2)}
        </span>
      </div>

      <div className="personas">
        {brief.personas.map((p) => (
          <div key={p.name} className="persona-chip" title={p.lens}>
            <span>{p.name}</span>
            <span className="persona-weight">{p.weight.toFixed(2)}</span>
          </div>
        ))}
      </div>

      <div className="consensus">
        {brief.convergence.length > 0 && (
          <div>
            <strong>Convergence:</strong> {brief.convergence.join(", ")}
          </div>
        )}
        {brief.dissent.length > 0 && (
          <div>
            <strong>Dissent:</strong> {brief.dissent.join(", ")}
          </div>
        )}
      </div>
    </section>
  );
}
