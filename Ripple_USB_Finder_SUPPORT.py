import os
import psutil

class Ripple_USBFinder:
    def __init__(self, target_drive_name="BIONICS_USB", status_callback=None):
        self.target_drive_name = target_drive_name
        self.partition_path = None
        self.vol_name = None
        self.status_callback = status_callback

    def find_usb_drive(self):
        """Scans for the target USB drive and updates class attributes if found."""
        for partition in psutil.disk_partitions():
            # Skip non-removable drives (works best on Windows)
            if 'removable' not in partition.opts:
                continue
            try:
                if os.name == 'nt':
                    import win32api
                    vol_name = win32api.GetVolumeInformation(partition.mountpoint)[0]
                    if vol_name == self.target_drive_name:
                        self.vol_name = vol_name
                        self.partition_path = partition.mountpoint
                        if self.status_callback:
                            self.status_callback(f"[USBFinder] Found {vol_name} at {self.partition_path}")
                        return self.partition_path
                else:
                    # Linux/Mac fallback check
                    if self.target_drive_name in partition.mountpoint:
                        self.vol_name = self.target_drive_name
                        self.partition_path = partition.mountpoint
                        return self.partition_path
            except Exception:
                # Catch permission errors on system partitions or unformatted drives
                continue
                
        return None

if __name__ == "__main__":
    Finder = Ripple_USBFinder("BIONICS_USB")
    path = Finder.find_usb_drive()
    
    # Safely handle the case where the USB is not plugged in
    if path:
        full_path = os.path.join(path, "Data")
        print(f"[SUCCESS] Drive found! vol_name: {Finder.vol_name} ; path: {full_path}")
        os.mkdir(full_path)
        print(f"[USBFinder] Directory Made !!")
    else:
        # Fallback to the current working directory where the PyInstaller .exe is running
        full_path = os.path.join(os.getcwd(), "Data")
        print(f"[WARNING] BIONICS_USB not found. Defaulting to local path: {full_path}")