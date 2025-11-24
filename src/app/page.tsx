import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Lexon",
  description: "A community-governed legal knowledge graph for transparent reasoning and trusted AI.",
};

export default function Home() {
  return (
    <div className="landing-wrapper">
      <style dangerouslySetInnerHTML={{
        __html: `
        .landing-wrapper {
          width: 100%;
          min-height: 100vh;
          background: #f6f4ef;
          font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
          color: #2b2b2b;
          line-height: 1.6;
          margin: 0;
          padding: 0;
          position: absolute;
          left: 0;
          right: 0;
          top: 0;
        }
        main {
          max-width: 1000px;
          margin: 0 auto;
          padding: 60px 32px 80px;
          text-align: center;
        }
        section {
          border: 2px dashed #dcd7cf;
          padding: 40px 32px;
          margin-bottom: 48px;
          border-radius: 12px;
          text-align: center;
          background: rgba(255, 255, 255, 0.3);
        }
        h1 {
          font-size: 42px;
          font-weight: 700;
          margin: 0 0 24px 0;
          line-height: 1.2;
          letter-spacing: -0.02em;
        }
        h2 {
          font-size: 32px;
          font-weight: 600;
          margin: 0 0 20px 0;
          line-height: 1.3;
          letter-spacing: -0.01em;
        }
        h3 {
          font-size: 22px;
          font-weight: 600;
          margin: 32px 0 16px 0;
          line-height: 1.4;
        }
        p {
          margin: 16px 0;
          font-size: 18px;
          line-height: 1.7;
          max-width: 800px;
          margin-left: auto;
          margin-right: auto;
        }
        .subheading {
          color: #8b887f;
          font-size: 20px;
          font-weight: 500;
          margin: 24px 0;
          line-height: 1.6;
        }
        .cta-row {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
          margin: 32px 0;
          justify-content: center;
        }
        .btn {
          padding: 16px 32px;
          border-radius: 10px;
          border: 2px dashed #c6d7f0;
          background: #e6eef8;
          font-weight: 600;
          font-size: 18px;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          transition: all 0.2s ease;
          text-decoration: none;
          color: inherit;
        }
        .btn:hover {
          background: #d6e0f0;
          border-color: #a8c0e0;
          transform: translateY(-2px);
        }
        .columns {
          display: flex;
          gap: 24px;
          flex-wrap: wrap;
          justify-content: center;
          margin: 32px 0;
        }
        .column {
          flex: 1 1 220px;
          font-size: 18px;
          font-weight: 500;
          padding: 16px;
          background: rgba(255, 255, 255, 0.5);
          border-radius: 8px;
        }
        ul {
          margin: 32px auto;
          padding-left: 24px;
          list-style-type: disc;
          display: inline-block;
          text-align: left;
          max-width: 800px;
        }
        li {
          display: list-item;
          list-style-position: outside;
          margin: 12px 0;
          font-size: 17px;
          line-height: 1.7;
          padding-left: 8px;
        }
        .quote {
          font-style: italic;
          border-left: 3px solid #c6d7f0;
          padding-left: 20px;
          margin: 32px auto;
          font-size: 19px;
          line-height: 1.6;
          color: #4a5568;
          max-width: 700px;
          text-align: left;
        }
        .footer {
          margin-top: 60px;
          font-size: 15px;
          color: #8b887f;
          text-align: center;
          font-style: italic;
          padding-top: 40px;
          border-top: 1px dashed #dcd7cf;
        }
        @media (max-width: 768px) {
          main {
            padding: 40px 20px 60px;
          }
          h1 {
            font-size: 32px;
          }
          h2 {
            font-size: 26px;
          }
          section {
            padding: 32px 24px;
            margin-bottom: 36px;
          }
          p {
            font-size: 16px;
          }
          .btn {
            padding: 14px 28px;
            font-size: 16px;
          }
        }
        `
      }} />
      <main>
        {/* HERO */}
        <section>
          <h1>Lexon: Building the Cognitive Core of Law</h1>
          <div className="cta-row">
            <a href="/whitepaper.pdf" target="_blank" rel="noopener noreferrer" className="btn">📘 Read the White Paper</a>
          </div>
          <p className="subheading">A community-governed legal knowledge graph for transparent reasoning and trusted AI.</p>
          <p>Lexon transforms unstructured legal data into a shared, verifiable foundation for research and AI. Built by legal stewards. Owned by the community.</p>
        </section>

        {/* PROBLEM */}
        <section>
          <h2>Law Runs on Reasoning—But Our Data Doesn&apos;t</h2>
          <div className="columns">
            <div className="column">Unstructured Logic</div>
            <div className="column">Duplicated Work</div>
            <div className="column">AI Hallucination</div>
          </div>
          <p>Legal research still depends on unstructured text, siloed insights, and duplicated work. When this data feeds into AI, it produces hallucinated citations, misread doctrines, and untrustworthy outputs.</p>
          <p className="quote">&ldquo;Without structured knowledge, even the smartest model cannot reason.&rdquo;</p>
        </section>

        {/* SOLUTION */}
        <section>
          <h2>A Shared, Evolving Legal Graph</h2>
          <p>Lexon structures legal reasoning—linking facts, doctrines, and policies into an evolving map of how law actually works. Built collaboratively, each annotation and debate becomes part of a transparent and verifiable record.</p>
        </section>

        {/* LEGAL STEWARDS */}
        <section>
          <h2>Shape the Future of Legal Reasoning</h2>
          <p>Lexon is built for legal professionals who see stewardship as legacy. As a Legal Steward, you contribute to the shared infrastructure of reasoning that powers both human and AI understanding.</p>
        </section>

        {/* INVESTORS */}
        <section>
          <h2>A Sustainable Model for Legal Intelligence</h2>
          <p>Legal AI is booming—but it lacks one thing: trusted data. Lexon provides the cognitive core that every serious legal AI tool will need—a verifiable, expert-built foundation.</p>
        </section>

        {/* IMPACT */}
        <section>
          <h2>Building a Transparent and Sustainable Future</h2>
          <p>🌱 Ethical AI Training: Transparent, peer-reviewed data ensures models learn from verified reasoning, not bias or noise.</p>
          <p>⚡ Sustainability: Structured data reduces computational waste and energy use—making legal AI greener and faster.</p>
          <p>🌍 Shared Ownership: By decentralizing legal knowledge, Lexon empowers communities, not corporations, to define the law&apos;s logic.</p>
        </section>

        {/* FINAL CTA */}
        <section>
          <h2>Help Build the Shared Infrastructure of Law</h2>
          <p>The logic of law should be transparent, auditable, and community-driven. Join us in shaping the cognitive core for human and AI reasoning alike.</p>
        </section>

        <div className="footer">&ldquo;The law, like the traveler, must be ready for the morrow.&rdquo; — Benjamin Cardozo</div>
      </main>
    </div>
  );
}
