"""
Visualization Module
Provides plot widgets for real-time data visualization.
"""

import numpy as np
from typing import Optional, Tuple
from abc import ABC, abstractmethod


class PlotWidget(ABC):
    """Abstract base class for plot widgets."""
    
    @abstractmethod
    def plot_waveform(self, data: np.ndarray, sample_rate: int) -> None:
        """Plot time-domain waveform."""
        pass
    
    @abstractmethod
    def plot_spectrum(self, frequencies: np.ndarray, magnitude: np.ndarray) -> None:
        """Plot frequency spectrum."""
        pass
    
    @abstractmethod
    def plot_spectrogram(
        self,
        frequencies: np.ndarray,
        times: np.ndarray,
        spectrogram: np.ndarray,
    ) -> None:
        """Plot spectrogram."""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all plots."""
        pass


class MatplotlibPlotWidget(PlotWidget):
    """Plot widget using Matplotlib."""
    
    def __init__(self):
        """Initialize matplotlib plot widget."""
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
            self.plt = plt
            self.Figure = Figure
            self.FigureCanvas = FigureCanvas
        except ImportError:
            raise ImportError("matplotlib required for plotting")
        
        self.figure = None
        self.axes = {}
        self._setup_figure()
    
    def _setup_figure(self) -> None:
        """Setup matplotlib figure."""
        self.figure = self.Figure(figsize=(10, 8), dpi=100)
        self.axes = {
            'waveform': self.figure.add_subplot(3, 1, 1),
            'spectrum': self.figure.add_subplot(3, 1, 2),
            'spectrogram': self.figure.add_subplot(3, 1, 3),
        }
        self.figure.tight_layout()
    
    def plot_waveform(self, data: np.ndarray, sample_rate: int) -> None:
        """Plot time-domain waveform."""
        ax = self.axes['waveform']
        ax.clear()
        
        if data.ndim > 1:
            data = data[:, 0]
        
        time = np.arange(len(data)) / sample_rate
        ax.plot(time, data, linewidth=0.5)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Amplitude")
        ax.set_title("Time-Domain Waveform")
        ax.grid(True, alpha=0.3)
        self.figure.canvas.draw()
    
    def plot_spectrum(self, frequencies: np.ndarray, magnitude: np.ndarray) -> None:
        """Plot frequency spectrum."""
        ax = self.axes['spectrum']
        ax.clear()
        
        ax.semilogx(frequencies, magnitude, linewidth=1)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Magnitude (dB)")
        ax.set_title("Frequency Spectrum")
        ax.grid(True, alpha=0.3, which='both')
        self.figure.canvas.draw()
    
    def plot_spectrogram(
        self,
        frequencies: np.ndarray,
        times: np.ndarray,
        spectrogram: np.ndarray,
    ) -> None:
        """Plot spectrogram."""
        ax = self.axes['spectrogram']
        ax.clear()
        
        pcm = ax.pcolormesh(
            times,
            frequencies,
            spectrogram,
            shading='auto',
            cmap='viridis',
        )
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Frequency (Hz)")
        ax.set_title("Spectrogram")
        self.figure.colorbar(pcm, ax=ax, label="Magnitude (dB)")
        self.figure.canvas.draw()
    
    def clear(self) -> None:
        """Clear all plots."""
        for ax in self.axes.values():
            ax.clear()
        self.figure.canvas.draw()


class PyQtGraphPlotWidget(PlotWidget):
    """Plot widget using PyQtGraph for better performance."""
    
    def __init__(self):
        """Initialize PyQtGraph plot widget."""
        try:
            import pyqtgraph as pg
            self.pg = pg
        except ImportError:
            raise ImportError("pyqtgraph required for plotting")
        
        self.plots = {}
    
    def plot_waveform(self, data: np.ndarray, sample_rate: int) -> None:
        """Plot time-domain waveform."""
        if data.ndim > 1:
            data = data[:, 0]
        
        time = np.arange(len(data)) / sample_rate
        
        if 'waveform' not in self.plots:
            self.plots['waveform'] = self.pg.plot(title="Time-Domain Waveform")
            self.plots['waveform'].setLabel('bottom', 'Time', units='s')
            self.plots['waveform'].setLabel('left', 'Amplitude')
        
        self.plots['waveform'].plot(time, data, pen='b')
    
    def plot_spectrum(self, frequencies: np.ndarray, magnitude: np.ndarray) -> None:
        """Plot frequency spectrum."""
        if 'spectrum' not in self.plots:
            self.plots['spectrum'] = self.pg.plot(title="Frequency Spectrum")
            self.plots['spectrum'].setLabel('bottom', 'Frequency', units='Hz')
            self.plots['spectrum'].setLabel('left', 'Magnitude', units='dB')
            self.plots['spectrum'].setLogMode(x=True)
        
        self.plots['spectrum'].plot(frequencies, magnitude, pen='r')
    
    def plot_spectrogram(
        self,
        frequencies: np.ndarray,
        times: np.ndarray,
        spectrogram: np.ndarray,
    ) -> None:
        """Plot spectrogram."""
        if 'spectrogram' not in self.plots:
            self.plots['spectrogram'] = self.pg.ImageView(title="Spectrogram")
        
        # Note: PyQtGraph image view expects different data format
        self.plots['spectrogram'].setImage(spectrogram)
    
    def clear(self) -> None:
        """Clear all plots."""
        for plot in self.plots.values():
            plot.clear()


# Factory function
def create_plot_widget(backend: str = "matplotlib") -> PlotWidget:
    """
    Factory function to create plot widget.
    
    Args:
        backend: Plot backend ('matplotlib', 'pyqtgraph')
    
    Returns:
        PlotWidget instance
    """
    if backend == "matplotlib":
        return MatplotlibPlotWidget()
    elif backend == "pyqtgraph":
        return PyQtGraphPlotWidget()
    else:
        raise ValueError(f"Unsupported plot backend: {backend}")
