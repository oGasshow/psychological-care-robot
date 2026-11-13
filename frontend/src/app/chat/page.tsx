'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { assistantDisplayText } from '@/lib/display-text';

interface Message {
  id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  phase?: string;
  isResolution?: boolean;
  isCrisis?: boolean;
}

interface ConversationMeta {
  conversation_id: number | null;
  phase: 'emotional' | 'rational' | 'solution';
  round_count: number;
  is_privacy: boolean;
  is_complex: boolean;
}

export default function ChatPage() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isClearing, setIsClearing] = useState(false); // 添加清空状态标志
  const [conversationMeta, setConversationMeta] = useState<ConversationMeta>({
    conversation_id: null,
    phase: 'emotional',
    round_count: 0,
    is_privacy: false,
    is_complex: false,
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      router.push('/login');
    }
  }, [router]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || loading || isClearing) return; // 清空中禁止发送

    const userMessage = input.trim();
    setInput('');
    setLoading(true);

    const tempUserMsg: Message = {
      id: Date.now(),
      role: 'user',
      content: userMessage,
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, tempUserMsg]);

    try {
      const token = localStorage.getItem('access_token');
      const response = await fetch('/api/chat/send', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: userMessage,
          conversation_id: conversationMeta.conversation_id,
        }),
      });

      if (!response.ok) {
        throw new Error('发送失败');
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let aiResponse = '';
      const currentMsgId = Date.now() + 1;

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                
                if (data.type === 'metadata') {
                  setConversationMeta({
                    conversation_id: data.conversation_id,
                    phase: data.phase,
                    round_count: data.round_count,
                    is_privacy: data.is_privacy,
                    is_complex: data.is_complex,
                  });
                  
                  const tempAiMsg: Message = {
                    id: currentMsgId,
                    role: 'assistant',
                    content: '',
                    created_at: new Date().toISOString(),
                    phase: data.phase,
                  };
                  setMessages(prev => [...prev, tempAiMsg]);
                  
                } else if (data.type === 'chunk') {
                  aiResponse += data.content;
                  setMessages(prev => {
                    const newMessages = [...prev];
                    const lastMsg = newMessages[newMessages.length - 1];
                    if (lastMsg && lastMsg.role === 'assistant') {
                      lastMsg.content = aiResponse;
                    }
                    return newMessages;
                  });
                  
                } else if (data.type === 'crisis') {
                  const crisisMsg: Message = {
                    id: currentMsgId,
                    role: 'system',
                    content: data.content,
                    created_at: new Date().toISOString(),
                    isCrisis: true,
                  };
                  setMessages(prev => [...prev, crisisMsg]);
                  
                } else if (data.type === 'end') {
                  break;
                }
              } catch (e) {
                // 静默忽略解析错误
              }
            }
          }
        }
      }
    } catch (error: unknown) {
      alert('发送失败：' + (error instanceof Error ? error.message : '网络错误，请重试'));
      setMessages(prev => prev.slice(0, -1));
    } finally {
      setLoading(false);
    }
  };

  const clearChat = async () => {
    if (!confirm('确定要清空对话吗？')) return;
    
    // 设置清空状态，防止在清空过程中发送消息
    setIsClearing(true);

    try {
      const token = localStorage.getItem('access_token');
      const response = await fetch('/api/chat/clear', {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      const data = await response.json();
      
      // 显示温暖的结束语
      if (data.success && data.message) {
        const farewell: Message = {
          id: Date.now(),
          role: 'assistant',
          content: data.message,
          created_at: new Date().toISOString(),
          isResolution: true,
        };
        setMessages(prev => [...prev, farewell]);
        
        // 3秒后清空（使用独立的清空逻辑）
        setTimeout(() => {
          setMessages([]);
          setConversationMeta({
            conversation_id: null,
            phase: 'emotional',
            round_count: 0,
            is_privacy: false,
            is_complex: false,
          });
          setIsClearing(false); // 清空完成
        }, 3000);
      } else {
        // 如果没有返回消息，直接清空
        setMessages([]);
        setConversationMeta({
          conversation_id: null,
          phase: 'emotional',
          round_count: 0,
          is_privacy: false,
          is_complex: false,
        });
        setIsClearing(false);
      }
    } catch (error) {
      alert('清空失败');
      setIsClearing(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gradient-to-br from-pink-50 via-purple-50 to-blue-50">
      {/* 顶部导航 */}
      <nav className="bg-white/80 backdrop-blur-md shadow-sm px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push('/dashboard')}
              className="text-gray-600 hover:text-gray-800 transition-colors"
            >
              ← 返回
            </button>
            <div className="flex items-center gap-2">
              <span className="text-2xl">🤖</span>
              <span className="text-xl font-bold bg-gradient-to-r from-pink-500 to-purple-600 bg-clip-text text-transparent">
                智能对话
              </span>
            </div>
          </div>
          <button
            onClick={clearChat}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
          >
            清空对话
          </button>
        </div>
      </nav>

      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-4xl mx-auto space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-20">
              <div className="text-6xl mb-4">💭</div>
              <p className="text-gray-600 text-lg">我是你的 24 小时心理陪伴助手</p>
              <p className="text-gray-400 text-sm mt-2">无论你遇到什么困扰，我都会倾听并陪你一起面对</p>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {msg.role === 'system' && msg.isCrisis ? (
                <div className="w-full max-w-[90%] rounded-2xl px-6 py-4 bg-red-50 border-2 border-red-300">
                  <div className="flex items-start gap-3">
                    <span className="text-3xl">🆘</span>
                    <div className="flex-1">
                      <div className="font-bold text-red-800 mb-2">检测到危机信号</div>
                      <div className="text-red-700 whitespace-pre-wrap">{assistantDisplayText(msg.content)}</div>
                    </div>
                  </div>
                </div>
              ) : msg.isResolution ? (
                <div className="w-full max-w-[90%] rounded-2xl px-6 py-4 bg-gradient-to-r from-green-50 to-blue-50 border-2 border-green-300">
                  <div className="flex items-start gap-3">
                    <span className="text-3xl">✨</span>
                    <div className="flex-1">
                      <div className="font-bold text-green-800 mb-2">问题已解决</div>
                      <div className="text-green-700 whitespace-pre-wrap">{assistantDisplayText(msg.content)}</div>
                      <div className="text-sm text-green-600 mt-2">对话将在 3 秒后自动清空...</div>
                    </div>
                  </div>
                </div>
              ) : (
                <div
                  className={`max-w-[70%] rounded-2xl px-6 py-4 ${
                    msg.role === 'user'
                      ? 'bg-gradient-to-r from-pink-500 to-purple-600 text-white'
                      : 'bg-white shadow-md text-gray-800'
                  }`}
                >
                  {msg.role === 'user' ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : msg.content ? (
                    <div className="prose prose-sm max-w-none prose-headings:mt-3 prose-headings:mb-2 prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-100 prose-pre:border prose-pre:border-gray-300">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {assistantDisplayText(msg.content)}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <span className="text-gray-400">思考中...</span>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* 输入区域 */}
      <div className="bg-white border-t border-gray-200 px-4 py-4">
        <div className="max-w-4xl mx-auto flex gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !isClearing) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder={isClearing ? "清空中，请稍候..." : "说说你的感受..."}
            disabled={loading || isClearing}
            className="flex-1 px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none disabled:bg-gray-100"
            rows={3}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim() || isClearing}
            className="px-8 py-3 bg-gradient-to-r from-pink-500 to-purple-600 text-white rounded-xl font-semibold hover:shadow-lg transform hover:scale-105 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none"
          >
            {loading ? '发送中...' : isClearing ? '清空中...' : '发送'}
          </button>
        </div>
      </div>
    </div>
  );
}
