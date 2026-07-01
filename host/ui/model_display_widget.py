"""
Model Display Widget
Displays FFT comparison between original and modeled signals.
"""

import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np
from processing.fft_tools import compute_fft
from scipy.stats import beta as beta_dist


class ModelDisplayWidget(QWidget):
    """Widget for displaying FFT comparison of original vs modeled signals."""
    
    def __init__(self):
        super().__init__()
        self.original_data = None
        self.original_sample_rate = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # FFT display group
        display_group = QGroupBox("FFT Comparison")
        display_layout = QVBoxLayout()
        
        # Info label
        self.info_label = QLabel("No recording loaded")
        self.info_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #ef6673;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        display_layout.addWidget(self.info_label)
        
        # Setup pyqtgraph plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#ffffff")
        self.plot_widget.setLabel('left', 'Magnitude', units='dB')
        self.plot_widget.setLabel('bottom', 'Frequency', units='Hz')
        self.plot_widget.setTitle('FFT Spectrum Comparison')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setMinimumHeight(160)
        self.plot_widget.setLogMode(x=True, y=False)
        
        # Configure plot appearance
        self.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color="#617086", width=1))
        self.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color="#617086", width=1))
        self.plot_widget.getPlotItem().getAxis('left').setTextPen("#263246")
        self.plot_widget.getPlotItem().getAxis('bottom').setTextPen("#263246")
        
        # Add legend
        self.plot_widget.addLegend()
        
        display_layout.addWidget(self.plot_widget)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        self.setLayout(layout)
    
    def set_original_recording(self, data: np.ndarray, sample_rate: int):
        """
        Set the original recording and display its FFT.
        
        Args:
            data: Original signal data
            sample_rate: Sample rate in Hz
        """
        self.original_data = data
        self.original_sample_rate = sample_rate
        
        # Clear and plot original FFT
        self.plot_widget.clear()
        
        # Compute FFT
        freqs, mag_db = compute_fft(data, sample_rate, fft_size=self._fft_size_for(data))
        
        # Plot original
        pen_original = pg.mkPen(color="#0aa9e8", width=2)
        self.plot_widget.plot(freqs, mag_db, pen=pen_original, name='Original')
        
        # Update info
        self.info_label.setText(f"Original Signal | Sample Rate: {sample_rate} Hz")
        self.info_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #263246;")
    
    def update_model_display(self, reconstructed_data: np.ndarray, model_name: str, model_parameters: dict | None = None):
        """
        Update display with modeled signal FFT.
        
        Args:
            reconstructed_data: Reconstructed signal from model
            model_name: Name of the model used
        """
        if self.original_data is None:
            return
        
        # Clear previous plots
        self.plot_widget.clear()
        
        # Plot original FFT
        freqs_orig, mag_db_orig = compute_fft(self.original_data, self.original_sample_rate, fft_size=self._fft_size_for(self.original_data))
        pen_original = pg.mkPen(color="#0aa9e8", width=2)
        self.plot_widget.plot(freqs_orig, mag_db_orig, pen=pen_original, name='Original')
        
        # Plot reconstructed FFT
        freqs_recon, mag_db_recon = compute_fft(reconstructed_data, self.original_sample_rate, fft_size=self._fft_size_for(reconstructed_data))
        pen_recon = pg.mkPen(color="#ef6673", width=2)
        self.plot_widget.plot(freqs_recon, mag_db_recon, pen=pen_recon, name=f'{model_name} Model')

        self._plot_model_representation(model_name, model_parameters or {}, freqs_orig, mag_db_orig, mag_db_recon)
        
        # Update info
        self.info_label.setText(f"Model: {model_name} | Sample Rate: {self.original_sample_rate} Hz")
        self.info_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #263246;")

    def _plot_model_representation(
        self,
        model_name: str,
        parameters: dict,
        freqs: np.ndarray,
        original_mag_db: np.ndarray,
        reconstructed_mag_db: np.ndarray | None = None,
    ):
        """Overlay the stored model representation in green."""
        if not parameters:
            return

        model_key = model_name.lower().replace(" ", "_")
        if model_key == "mfcc":
            self._plot_mfcc_representation(parameters, freqs, original_mag_db, reconstructed_mag_db)
        elif model_key == "speak":
            self._plot_speak_representation(parameters, freqs, original_mag_db)
        elif model_key == "sbeta":
            self._plot_sbeta_representation(parameters, freqs, original_mag_db)
        elif model_key in ("spectral_slope", "sslope"):
            self._plot_slope_representation(parameters, freqs, original_mag_db)

    def _plot_speak_representation(self, parameters: dict, freqs: np.ndarray, original_mag_db: np.ndarray):
        peak_freqs = np.asarray(parameters.get("frequencies", []), dtype=np.float64)
        if len(peak_freqs) == 0:
            return
        visible = (peak_freqs >= freqs[0]) & (peak_freqs <= freqs[-1])
        peak_freqs = peak_freqs[visible]
        if len(peak_freqs) == 0:
            return
        peak_db = np.interp(peak_freqs, freqs, original_mag_db)
        self.plot_widget.plot(
            peak_freqs,
            peak_db,
            pen=None,
            symbol="o",
            symbolBrush=pg.mkBrush(0, 180, 0, 190),
            symbolPen=pg.mkPen(color=(0, 140, 0), width=1.5),
            symbolSize=9,
            name="Stored sPeak frequencies",
        )

    def _plot_mfcc_representation(
        self,
        parameters: dict,
        freqs: np.ndarray,
        original_mag_db: np.ndarray,
        reconstructed_mag_db: np.ndarray | None,
    ):
        band_freqs = np.asarray(parameters.get("band_frequencies", []), dtype=np.float64)
        energies = np.asarray(parameters.get("band_energies", []), dtype=np.float64)
        band_edges = np.asarray(parameters.get("band_edges", []), dtype=np.float64)
        self._plot_mfcc_triangles(band_edges, band_freqs, freqs, original_mag_db, reconstructed_mag_db)
        if len(band_freqs) == 0 or len(energies) == 0:
            return
        count = min(len(band_freqs), len(energies))
        band_freqs = band_freqs[:count]
        band_db = 10.0 * np.log10(np.maximum(energies[:count], 1e-12))
        visible = (band_freqs >= freqs[0]) & (band_freqs <= freqs[-1])
        band_freqs = band_freqs[visible]
        band_db = band_db[visible]
        if len(band_freqs) == 0:
            return
        band_db = self._align_overlay_peak(band_db, np.interp(band_freqs, freqs, original_mag_db))
        self.plot_widget.plot(
            band_freqs,
            band_db,
            pen=pg.mkPen(color=(0, 150, 0), width=2),
            symbol="o",
            symbolBrush=pg.mkBrush(0, 180, 0, 180),
            symbolPen=pg.mkPen(color=(0, 120, 0), width=1),
            symbolSize=7,
            name="Stored MFCC band energies",
        )

    def _plot_mfcc_triangles(
        self,
        band_edges: np.ndarray,
        band_centers: np.ndarray,
        freqs: np.ndarray,
        original_mag_db: np.ndarray,
        reconstructed_mag_db: np.ndarray | None,
    ):
        if len(band_edges) < 3:
            return
        visible = (freqs >= band_edges[0]) & (freqs <= band_edges[-1])
        if np.any(visible):
            reference = original_mag_db[visible]
        else:
            reference = original_mag_db
        top = float(np.nanmax(reference))
        bottom_candidates = [np.asarray(original_mag_db, dtype=np.float64)]
        if reconstructed_mag_db is not None:
            bottom_candidates.append(np.asarray(reconstructed_mag_db, dtype=np.float64))
        bottom = float(np.nanmin(np.concatenate([values[np.isfinite(values)] for values in bottom_candidates if np.any(np.isfinite(values))])))
        if not np.isfinite(top) or not np.isfinite(bottom) or top <= bottom:
            top, bottom = 0.0, -60.0
        peak = top

        for index in range(len(band_edges) - 2):
            left = band_edges[index]
            center = band_centers[index] if index < len(band_centers) else band_edges[index + 1]
            right = band_edges[index + 2]
            if right < freqs[0] or left > freqs[-1]:
                continue
            if not (left < center < right):
                center = band_edges[index + 1]
            self.plot_widget.plot(
                [left, center, right],
                [bottom, peak, bottom],
                pen=pg.mkPen(color=(0, 150, 0, 80), width=1),
                name="MFCC triangular bands" if index == 0 else None,
            )

    def _plot_sbeta_representation(self, parameters: dict, freqs: np.ndarray, original_mag_db: np.ndarray):
        low = float(parameters.get("freq_low", 20.0))
        high = float(parameters.get("freq_high", 1000.0))
        mask = (freqs >= low) & (freqs <= high)
        if not np.any(mask):
            return
        plot_freqs = freqs[mask]
        log_low = np.log10(low)
        log_high = np.log10(high)
        x = (np.log10(np.maximum(plot_freqs, low)) - log_low) / max(1e-9, log_high - log_low)
        envelope = (
            float(parameters.get("scale", 1.0))
            * float(parameters.get("peak_level", 1.0))
            * beta_dist.pdf(np.clip(x, 1e-4, 1.0 - 1e-4), parameters.get("alpha", 2.0), parameters.get("beta", 5.0))
        )
        envelope_db = 20.0 * np.log10(np.maximum(envelope, 1e-12))
        envelope_db = self._align_overlay_peak(envelope_db, original_mag_db[mask])
        self.plot_widget.plot(
            plot_freqs,
            envelope_db,
            pen=pg.mkPen(color=(0, 150, 0), width=3),
            name="Stored sBeta shape",
        )

    def _plot_slope_representation(self, parameters: dict, freqs: np.ndarray, original_mag_db: np.ndarray):
        low = float(parameters.get("freq_low", 20.0))
        high = float(parameters.get("freq_high", 1000.0))
        peak = float(parameters.get("peak_freq", 120.0))
        rise_order = max(1, int(parameters.get("rise_order", 1)))
        fall_order = max(1, int(parameters.get("fall_order", 1)))
        mask = (freqs >= low) & (freqs <= high)
        if not np.any(mask):
            return
        plot_freqs = freqs[mask]
        shape_db = np.zeros_like(plot_freqs, dtype=np.float64)
        left = plot_freqs < peak
        right = ~left
        shape_db[left] = -20.0 * rise_order * np.log10(np.maximum(peak / np.maximum(plot_freqs[left], low), 1.0))
        shape_db[right] = -20.0 * fall_order * np.log10(np.maximum(plot_freqs[right] / max(peak, 1e-9), 1.0))
        shape_db = self._align_overlay_peak(shape_db, original_mag_db[mask])
        self.plot_widget.plot(
            plot_freqs,
            shape_db,
            pen=pg.mkPen(color=(0, 150, 0), width=3),
            name="Stored sSlope shape",
        )

    @staticmethod
    def _align_overlay_peak(overlay_db: np.ndarray, reference_db: np.ndarray) -> np.ndarray:
        if len(overlay_db) == 0 or len(reference_db) == 0:
            return overlay_db
        return overlay_db + (np.nanmax(reference_db) - np.nanmax(overlay_db))

    @staticmethod
    def _fft_size_for(data: np.ndarray) -> int:
        length = len(data)
        if length <= 4096:
            return 4096
        return int(2 ** np.ceil(np.log2(length)))
    
    def clear_display(self):
        """Clear the display."""
        self.plot_widget.clear()
        plot_item = self.plot_widget.getPlotItem()
        if plot_item.legend is not None:
            plot_item.legend.clear()
        self.info_label.setText("No recording loaded")
        self.info_label.setStyleSheet("font-weight: bold; font-size: 14px; color: red;")
        self.info_label.repaint()
        self.original_data = None
        self.original_sample_rate = None
