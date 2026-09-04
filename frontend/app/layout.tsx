import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MedNuskha",
  description:
    "Medication adherence for elderly patients, delivered over WhatsApp.",
  icons: {
    icon: "/mednuskha-logo.jpg",
    shortcut: "/mednuskha-logo.jpg",
    apple: "/mednuskha-logo.jpg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          Loaded with a plain <link> rather than next/font on purpose. next/font
          fetches at BUILD time, so a flaky network turns a missing font into a
          compile error and the site does not start at all. A link degrades to
          the fallback stack and the page still works - which matters more the
          morning of a demo than a few milliseconds of layout shift.
        */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href={
            "https://fonts.googleapis.com/css2?" +
            "family=Instrument+Sans:ital,wght@0,400..700;1,400..600&" +
            "family=Instrument+Serif:ital@0;1&" +
            "family=JetBrains+Mono:wght@400;500;700&" +
            "family=Noto+Naskh+Arabic:wght@400;600&display=swap"
          }
        />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
