/**
 * generate_po_token.mjs
 *
 * Generates a fresh YouTube PO token + visitor_data for yt-dlp.
 * Must be run once at the start of each pipeline execution.
 * Output is written to data/po_token.json and read by scraper.py + downloader.py.
 *
 * Usage: node generate_po_token.mjs
 *
 * Why this is needed:
 *   GitHub Actions IPs are flagged by YouTube as bots. yt-dlp needs a valid
 *   PO (Proof of Origin) token tied to a real browser session to bypass this.
 *   This script uses a headless Chrome to generate that token automatically —
 *   no manual cookies, no expiry issues.
 */

import { generate } from "youtube-po-token-generator";
import { writeFileSync, mkdirSync } from "fs";

async function main() {
  console.log("Generating YouTube PO token (headless Chrome)...");

  let result;
  try {
    result = await generate();
  } catch (err) {
    console.error("❌ PO token generation failed:", err.message);
    process.exit(1);
  }

  if (!result?.poToken || !result?.visitorData) {
    console.error("❌ PO token generation returned empty result");
    process.exit(1);
  }

  const out = {
    po_token: result.poToken,
    visitor_data: result.visitorData,
    generated_at: new Date().toISOString(),
  };

  mkdirSync("data", { recursive: true });
  writeFileSync("data/po_token.json", JSON.stringify(out, null, 2));

  console.log(`✓ po_token:     ${out.po_token.slice(0, 24)}...`);
  console.log(`✓ visitor_data: ${out.visitor_data.slice(0, 24)}...`);
  console.log(`✓ Saved to data/po_token.json`);
}

main();
