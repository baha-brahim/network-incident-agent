import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import localFont from "next/font/local";
import { SiteFooter } from "@/components/shell/site-footer";
import { SiteHeader } from "@/components/shell/site-header";
import { TipProvider } from "@/components/ui/tip";
import "./globals.css";

const display = localFont({
  src: "./fonts/FunnelDisplay-Variable.woff2",
  weight: "300 800",
  variable: "--font-funnel-display",
  display: "swap",
});

const sans = localFont({
  src: [
    { path: "./fonts/FunnelSans-Variable.woff2", weight: "300 800", style: "normal" },
    { path: "./fonts/FunnelSans-Italic-Variable.woff2", weight: "300 800", style: "italic" },
  ],
  variable: "--font-funnel-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Network Incident Agent", template: "%s · Network Incident Agent" },
  description:
    "Watch an agent investigate a telecom network incident step by step, and read a report where every claim cites its evidence.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  colorScheme: "light",
  themeColor: "#faf9f5",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${GeistMono.variable}`}>
      <body className="flex min-h-dvh flex-col antialiased">
        <a href="#content" className="btn is-primary sr-only focus:not-sr-only focus:fixed focus:left-[max(0.75rem,env(safe-area-inset-left))] focus:top-[max(0.75rem,env(safe-area-inset-top))] focus:z-50 focus:px-4">
          Skip to content
        </a>
        <TipProvider>
          <SiteHeader />
          <main id="content" tabIndex={-1} className="flex-1">
            {children}
          </main>
          <SiteFooter />
        </TipProvider>
      </body>
    </html>
  );
}
