import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/sidebar";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "RFP Responder — Dashboard",
  description: "AI-powered RFP pipeline automation dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className="antialiased">
      <body className="min-h-full flex font-sans" suppressHydrationWarning>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <Sidebar />
          <div className="flex-1 flex flex-col min-h-screen min-w-0 relative z-[1]">
            {children}
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
