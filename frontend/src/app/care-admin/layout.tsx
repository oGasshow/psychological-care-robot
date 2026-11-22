import '../robot-care/care.css';
import './management.css';
import CareAccount from '@/components/care-account';

export default function Layout({children}:{children:React.ReactNode}) {
  return <div className="care-root"><CareAccount requireManager>{children}</CareAccount></div>;
}
