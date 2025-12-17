import type { Metadata } from "next";
import Image from "next/image";

export const metadata: Metadata = {
  title: "Lexon",
  description: "Aligning human insight with AI power.",
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
          padding: 48px 40px;
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
        .brand-row {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 20px;
          flex-wrap: wrap;
          margin-bottom: 32px;
        }
        .brand-name {
          margin: 0;
          font-size: 46px;
          font-weight: 750;
          line-height: 1.05;
          letter-spacing: -0.03em;
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
          margin: 20px 0;
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
          margin: 0 auto 32px auto;
          line-height: 1.6;
        }
        .cta-row {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
          margin: 0 0 32px 0;
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
        .logo {
          display: block;
          margin: 0;
          width: auto;
          height: auto;
          max-width: 320px;
          max-height: 96px;
          object-fit: contain;
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
          .brand-row {
            gap: 0px;
            margin-bottom: 24px;
          }
          .brand-name {
            font-size: 36px;
          }
          .logo {
            max-width: 140px;
            max-height: 46px;
            width: auto;
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
          <div className="brand-row">
            <Image
              src="/logo.png"
              alt="Lexon logo"
              width={96}
              height={96}
              className="logo"
              priority
              unoptimized
            />
            <h1 className="brand-name">Lexon</h1>
          </div>
          <p className="subheading">Aligning Human Insight with AI Power</p>
          <div className="cta-row">
            <a href="/white-paper" target="_blank" rel="noopener noreferrer" className="btn">📘 Read the White Paper</a>
          </div>
          <p>We are building the bridge between legal expertise and artificial intelligence.</p>
          <p>Lexon transforms unstructured law into a verifiable foundation, ensuring AI amplifies lawyers rather than replacing them.</p>
        </section>

        {/* PROBLEM */}
        <section>
          <h2>The Problem: AI Needs a Pilot.</h2>
          <p>Current Legal AI is powerful, but it lacks the nuance of a jurist. Raw text feeds allow AI to hallucinate citations and miss subtle doctrines. This creates a dangerous &ldquo;alignment gap&rdquo; where tools generate risks instead of results.</p>
          <ul>
            <li><strong>The Risk:</strong> Without human logic, AI is a black box.</li>
            <li><strong>The Reality:</strong> Technology should not replace the lawyer; it should scale the lawyer&apos;s ability to deliver better outcomes.</li>
          </ul>
        </section>

        {/* SOLUTION */}
        <section>
          <h2>The Solution: Anchoring AI in Human Logic</h2>
          <p>We are building the Cognitive Core for law—a system where human expertise validates machine output. Lexon uses a Human-in-the-Loop (HITL) architecture. Instead of scraping data, we empower legal experts to structure it. By linking facts to issues, doctrines, and policies, we create a transparent &ldquo;Legal Graph&rdquo; that forces AI to reason the way lawyers do.</p>
          <ul>
            <li><strong>Trusted:</strong> Every data point is verifiable.</li>
            <li><strong>Transparent:</strong> No hidden logic.</li>
            <li><strong>Aligned:</strong> AI that acts as a true extension of your mind.</li>
          </ul>
        </section>

        {/* CALL TO ACTION */}
        <section>
          <h2>Call to Action: Be the Architect, Not the Passenger</h2>
          <p>At Lexon, we believe the future of law is human-centric. As a Legal Steward, you provide the expert oversight that AI desperately needs. Your contributions ensure that the next generation of legal tools are built on a foundation of verified truth, protecting the integrity of the profession.</p>
        </section>

        {/* IMPACT */}
        <section>
          <h2>Impact: Better Outcomes, Less Risk</h2>
          <p>When AI is grounded in expert-curated logic, everyone wins.</p>
          <ul>
            <li><strong>For Lawyers:</strong> Move from drudgery to strategy with tools you can actually trust.</li>
            <li><strong>For Clients:</strong> Receive faster, more accurate counsel based on verifiable data.</li>
            <li><strong>For the System:</strong> A sustainable, transparent legal infrastructure owned and managed by the community.</li>
          </ul>
        </section>

        <div className="footer">&ldquo;The law, like the traveler, must be ready for the morrow.&rdquo; — Benjamin Cardozo</div>
      </main>
    </div>
  );
}
