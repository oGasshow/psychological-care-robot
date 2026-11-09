import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "心理疏导机器人系统",
  description: "隐私优先的本地化 AI 心理健康管理系统，提供 24/7 智能对话、心理评估、训练指导等功能",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
