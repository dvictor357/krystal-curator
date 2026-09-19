import type { Metadata } from "next";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";
export const metadata: Metadata = {
  title: {
    default: "Curator — See both sides of the pool",
    template: "%s | Curator",
  },
  description:
    "An LP workspace for concentrated liquidity. Rank pairs by fees, depth, and risk. Private watchlist. Sign in with your wallet or email; no transactions.",
  metadataBase: process.env.CURATOR_ORIGIN
    ? new URL(process.env.CURATOR_ORIGIN)
    : undefined,
  openGraph: {
    title: "Curator — Should this position move? We keep score.",
    description:
      "Rotation verdicts with payback days, honest σ and spike flags, and a public track record judged against what really paid. Robinhood, Base, Ethereum, Arbitrum and more.",
    type: "website",
    siteName: "Curator",
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "Curator — LP research desk",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Curator — Should this position move?",
    description:
      "Per-position rotation verdicts, payback days and a public track record. Wallet sign-in, no transactions.",
    images: ["/og.png"],
  },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <a href="#main" className="skip">
          Skip to content
        </a>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
