import './care.css';
import CareAccount from '@/components/care-account';

export default function CareLayout({ children }: { children: React.ReactNode }) {
  return <div className="care-root"><CareAccount>{children}</CareAccount></div>;
}
