import ResourcePage from "./ResourcePage";
import DiskReadSpeed from "../components/disk/DiskReadSpeed";
import DiskIoHistory from "../components/history/DiskIoHistory";

export default function Disk() {
  return (
    <div className="disk-page-container">
      <ResourcePage resource="disk" />
      <DiskReadSpeed />
      <DiskIoHistory />
    </div>
  );
}
