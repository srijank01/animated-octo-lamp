import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoClip AI — Viral Short-Form Video Studio",
  description: "Transform long-form YouTube videos into high-retention 9:16 vertical shorts with smart face reframing and dynamic karaoke subtitles.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased dark font-sans">
      <body className="min-h-full flex flex-col bg-zinc-950 text-zinc-100">{children}</body>
    </html>
  );
}
