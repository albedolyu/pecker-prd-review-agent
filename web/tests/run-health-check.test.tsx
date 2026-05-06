import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RunHealthCheck } from "@/components/run/RunHealthCheck";

describe("RunHealthCheck", () => {
  it("uses the large reviewer portraits in the reviewer status cards", () => {
    const html = renderToStaticMarkup(
      <RunHealthCheck
        sessionClass="productive"
        consistency={0.92}
        failures={{}}
        birds={[
          { id: 1, runs: 1, fails: 0, submissions: 1 },
          { id: 2, runs: 1, fails: 0, submissions: 1 },
          { id: 3, runs: 1, fails: 0, submissions: 1 },
          { id: 4, runs: 1, fails: 0, submissions: 1 },
          { id: 5, runs: 1, fails: 0, submissions: 1 },
        ]}
        onContinue={() => {}}
        onRetry={() => {}}
      />,
    );

    expect(html).toContain('/birds/biz-lg.png');
    expect(html).toContain('/birds/data-lg.png');
    expect(html).toContain('/birds/ux-lg.png');
    expect(html).toContain('/birds/risk-lg.png');
    expect(html).toContain('/birds/goshawk-lg.png');
  });
});
