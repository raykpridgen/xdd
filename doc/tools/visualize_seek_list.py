#!/usr/bin/env python3
"""
XDD Seek List Visualizer

This script mimics the logic from xdd_init_seek_list() in init.c to visualize
how block locations are calculated with different stagger and interleave options.

The visualization shows:
- Operation blocks (color-coded by operation number)
- Gaps created by stagger (highlighted in one color)
- Gaps created by interleave (highlighted in another color)
"""
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import PatchCollection
import numpy as np
import argparse
matplotlib.use("TkAgg")

class SeekListVisualizer:
    """Visualizes XDD seek list block locations with stagger and interleave options."""

    def __init__(self, num_ops, block_size=1, start_offset=0, seek_range=None,
                 stagger=False, stagger_value=None, interleave=False, interleave_value=1,
                 num_instances=1):
        """
        Initialize the visualizer.

        Args:
            num_ops: Number of operations (seek_total_ops)
            block_size: Size of each block (td_block_size) - for visualization purposes
            start_offset: Starting offset (td_start_offset) - only used when num_instances=1
            seek_range: Total range for seeks (seek_range)
            stagger: Enable stagger mode
            stagger_value: If provided, use as stride; otherwise auto-calculate gap
            interleave: Enable interleave mode
            interleave_value: Interleave multiplier (seek_interleave)
            num_instances: Number of process instances to visualize
        """
        self.num_ops = num_ops
        self.block_size = block_size
        self.start_offset = start_offset
        self.stagger = stagger
        self.stagger_value = stagger_value
        self.interleave = interleave
        self.interleave_value = interleave_value if interleave else 1
        self.num_instances = num_instances

        # Calculate seek_range if not provided
        if seek_range is None:
            # Default range: enough to fit all operations
            self.seek_range = 1024
        else:
            self.seek_range = seek_range

        # For multi-instance mode
        self.instances = []  # List of (instance_id, block_locations, gap_info, start_offset)

        # For single-instance mode (backward compatibility)
        self.block_locations = []
        self.gap_info = []  # Store gap information for visualization

    def calculate_block_locations(self):
        """
        Calculate block locations based on the C code logic from init.c:109-133.

        Mimics the logic:
            if (sp->seek_options & SO_SEEK_STAGGER) {
                gap = (sp->seek_range - (sp->seek_num_rw_ops + 1)) / (sp->seek_num_rw_ops-1);
                if (sp->seek_stride > tdp->td_block_size)
                    gap = sp->seek_stride - tdp->td_block_size;
            } else {
                gap = 0;
            }

            if (sp->seek_interleave > 1)
                interleave_threadoffset = sp->seek_interleave;
            else
                interleave_threadoffset = 0;

            sp->seeks[rw_index].block_location = tdp->td_start_offset + interleave_threadoffset +
                                                (rw_op_index * (sp->seek_interleave + gap));
        """
        if self.num_instances > 1:
            # Multi-instance mode: calculate for each instance with appropriate start offset
            self._calculate_multi_instance()
        else:
            # Single-instance mode (original behavior)
            self._calculate_single_instance(self.start_offset)

        return self.block_locations

    def _calculate_single_instance(self, start_offset):
        """Calculate block locations for a single instance."""
        # Calculate gap for stagger
        if self.stagger:
            if self.stagger_value is not None and self.stagger_value > self.block_size:
                # Using stride mode
                gap = self.stagger_value - self.block_size
            else:
                # Auto-calculate gap
                gap = (self.seek_range - (self.num_ops + 1)) // (self.num_ops - 1) if self.num_ops > 1 else 0
        else:
            gap = 0

        # Calculate interleave offset
        if self.interleave_value > 1:
            interleave_threadoffset = self.interleave_value
        else:
            interleave_threadoffset = 0

        # Generate block locations
        block_locations = []
        for op_index in range(self.num_ops):
            # This is the core formula from init.c:132-133
            block_location = start_offset + interleave_threadoffset + \
                           (op_index * (self.interleave_value + gap))
            block_locations.append(block_location)

        # Calculate gap information for visualization
        gap_info = self._calculate_gaps(block_locations, gap, interleave_threadoffset, start_offset)

        return block_locations, gap_info

    def _calculate_multi_instance(self):
        """Calculate block locations for multiple instances with proper interleaving."""
        self.instances = []

        # For interleaving to work, each instance needs a different start offset
        # Instance 0: start_offset = 0 blocks
        # Instance 1: start_offset = 1 block
        # Instance 2: start_offset = 2 blocks
        # ...
        # This way, with interleave_value = num_instances, blocks weave together

        for instance_id in range(self.num_instances):
            # Calculate the start offset for this instance (in blocks, not bytes)
            instance_start_offset = instance_id

            # Calculate block locations for this instance
            block_locations, gap_info = self._calculate_single_instance(instance_start_offset)

            self.instances.append({
                'instance_id': instance_id,
                'start_offset': instance_start_offset,
                'block_locations': block_locations,
                'gap_info': gap_info
            })

    def _calculate_gaps(self, block_locations, stagger_gap, interleave_offset, start_offset):
        """
        Analyze gaps between blocks to determine what created them.

        Gaps can be created by:
        1. Interleave: Initial offset and spacing multiplier
        2. Stagger: Additional spacing between operations
        """
        gap_info = []

        # If we have an interleave offset at the start
        if interleave_offset > 0 and self.num_ops > 0:
            gap_info.append({
                'start': start_offset * self.block_size,
                'end': (start_offset + interleave_offset) * self.block_size,
                'type': 'interleave_offset',
                'description': f'Interleave initial offset ({interleave_offset} blocks)'
            })

        # Analyze gaps between consecutive operations
        for i in range(len(block_locations) - 1):
            block_end = (block_locations[i] + 1) * self.block_size
            next_block_start = block_locations[i + 1] * self.block_size

            if next_block_start > block_end:
                gap_size = (next_block_start - block_end) // self.block_size

                # Determine what created this gap
                # The spacing includes both interleave and stagger
                # Base spacing from interleave: interleave_value
                # Additional spacing from stagger: stagger_gap

                if self.interleave and self.stagger:
                    # Both contribute
                    interleave_contribution = self.interleave_value - 1
                    stagger_contribution = stagger_gap

                    if interleave_contribution > 0:
                        gap_info.append({
                            'start': block_end,
                            'end': block_end + (interleave_contribution * self.block_size),
                            'type': 'interleave',
                            'description': f'Interleave gap ({interleave_contribution} blocks)'
                        })

                    if stagger_contribution > 0:
                        gap_info.append({
                            'start': block_end + (interleave_contribution * self.block_size),
                            'end': next_block_start,
                            'type': 'stagger',
                            'description': f'Stagger gap ({stagger_contribution} blocks)'
                        })

                elif self.interleave:
                    # Only interleave
                    gap_info.append({
                        'start': block_end,
                        'end': next_block_start,
                        'type': 'interleave',
                        'description': f'Interleave gap ({gap_size} blocks)'
                    })

                elif self.stagger:
                    # Only stagger
                    gap_info.append({
                        'start': block_end,
                        'end': next_block_start,
                        'type': 'stagger',
                        'description': f'Stagger gap ({gap_size} blocks)'
                    })

        # For single-instance mode, also populate the instance variables
        if self.num_instances <= 1:
            self.block_locations = block_locations
            self.gap_info = gap_info

        return gap_info

    def visualize(self, title=None):
        """
        Create a visual representation of the block locations and gaps.
        """
        if self.num_instances <= 1 and not self.block_locations:
            self.calculate_block_locations()
        elif self.num_instances > 1 and not self.instances:
            self.calculate_block_locations()

        fig, ax = plt.subplots(figsize=(16, 8))

        # Color scheme
        if self.num_instances > 1:
            # In multi-instance mode, color by instance
            colors = {
                'instance': plt.cm.tab10(np.linspace(0, 1, self.num_instances)),
                'interleave_gap': '#FFE5B4',  # Light orange/peach
                'interleave_offset': '#FFD700',  # Gold
                'stagger_gap': '#ADD8E6',  # Light blue
                'unused': '#F0F0F0'  # Light gray
            }
        else:
            # In single-instance mode, color by operation
            colors = {
                'block': plt.cm.tab20(np.linspace(0, 1, self.num_ops)),
                'interleave_gap': '#FFE5B4',  # Light orange/peach
                'interleave_offset': '#FFD700',  # Gold
                'stagger_gap': '#ADD8E6',  # Light blue
                'unused': '#F0F0F0'  # Light gray
            }

        # Calculate the total range to display (in actual byte positions)
        if self.num_instances > 1:
            # Multi-instance mode
            all_locations = []
            for inst in self.instances:
                all_locations.extend(inst['block_locations'])
            if all_locations:
                max_location = (max(all_locations) + 1) * self.block_size
                display_range = max(max_location, self.seek_range * self.block_size) + self.block_size
            else:
                display_range = self.seek_range * self.block_size
        else:
            # Single-instance mode
            if self.block_locations:
                max_location = (max(self.block_locations) + 1) * self.block_size
                display_range = max(max_location, self.seek_range * self.block_size) + self.block_size
            else:
                display_range = self.seek_range * self.block_size

        if self.num_instances > 1:
            # Multi-instance visualization
            # First, collect all operation block positions to avoid drawing gaps over them
            all_operation_positions = set()
            for inst in self.instances:
                for location in inst['block_locations']:
                    # Store the byte range for each operation block
                    byte_start = location * self.block_size
                    byte_end = (location + 1) * self.block_size
                    all_operation_positions.add((byte_start, byte_end))

            # Draw gaps first, but only where there are no operations
            for inst in self.instances:
                gap_info = inst['gap_info']

                for gap in gap_info:
                    gap_type = gap['type']
                    if gap_type == 'interleave_offset':
                        color = colors['interleave_offset']
                    elif gap_type == 'interleave':
                        color = colors['interleave_gap']
                    else:  # stagger
                        color = colors['stagger_gap']

                    # Check if this gap overlaps with any operation block
                    gap_start = gap['start']
                    gap_end = gap['end']

                    # Split the gap into segments that don't overlap with operations
                    current_pos = gap_start
                    for op_start, op_end in sorted(all_operation_positions):
                        # If there's a gap segment before this operation
                        if current_pos < op_start and current_pos < gap_end:
                            segment_end = min(op_start, gap_end)
                            rect = mpatches.Rectangle(
                                (current_pos, 0), segment_end - current_pos, 1,
                                facecolor=color, edgecolor='none', linewidth=0,
                                alpha=0.5
                            )
                            ax.add_patch(rect)

                        # Skip past the operation block
                        if op_end > current_pos:
                            current_pos = max(current_pos, op_end)

                        # If we've passed the end of the gap, stop
                        if current_pos >= gap_end:
                            break

                    # Draw any remaining gap segment after the last operation
                    if current_pos < gap_end:
                        rect = mpatches.Rectangle(
                            (current_pos, 0), gap_end - current_pos, 1,
                            facecolor=color, edgecolor='none', linewidth=0,
                            alpha=0.5
                        )
                        ax.add_patch(rect)

            # Now draw operation blocks on top
            for inst in self.instances:
                instance_id = inst['instance_id']
                block_locations = inst['block_locations']
                instance_color = colors['instance'][instance_id]

                # Draw operation blocks for this instance
                for i, location in enumerate(block_locations):
                    display_location = location * self.block_size
                    rect = mpatches.Rectangle(
                        (display_location, 0), self.block_size, 1,
                        facecolor=instance_color, edgecolor='black', linewidth=1.5,
                        zorder=10  # Ensure operations are drawn on top
                    )
                    ax.add_patch(rect)

                    # Add label showing instance and operation
                    label = f'I{instance_id}:O{i}'
                    ax.text(display_location + self.block_size/2, 0.5, label,
                           ha='center', va='center', fontsize=7, fontweight='bold',
                           zorder=11)  # Labels on top of everything
        else:
            # Single-instance visualization (original)
            # Collect all operation block positions
            all_operation_positions = set()
            for location in self.block_locations:
                byte_start = location * self.block_size
                byte_end = (location + 1) * self.block_size
                all_operation_positions.add((byte_start, byte_end))

            # Draw gaps first (background), avoiding operation blocks
            for gap in self.gap_info:
                gap_type = gap['type']
                if gap_type == 'interleave_offset':
                    color = colors['interleave_offset']
                elif gap_type == 'interleave':
                    color = colors['interleave_gap']
                else:  # stagger
                    color = colors['stagger_gap']

                # Check if this gap overlaps with any operation block
                gap_start = gap['start']
                gap_end = gap['end']

                # Split the gap into segments that don't overlap with operations
                current_pos = gap_start
                for op_start, op_end in sorted(all_operation_positions):
                    # If there's a gap segment before this operation
                    if current_pos < op_start and current_pos < gap_end:
                        segment_end = min(op_start, gap_end)
                        rect = mpatches.Rectangle(
                            (current_pos, 0), segment_end - current_pos, 1,
                            facecolor=color, edgecolor='none', linewidth=0
                        )
                        ax.add_patch(rect)

                    # Skip past the operation block
                    if op_end > current_pos:
                        current_pos = max(current_pos, op_end)

                    # If we've passed the end of the gap, stop
                    if current_pos >= gap_end:
                        break

                # Draw any remaining gap segment after the last operation
                if current_pos < gap_end:
                    rect = mpatches.Rectangle(
                        (current_pos, 0), gap_end - current_pos, 1,
                        facecolor=color, edgecolor='none', linewidth=0
                    )
                    ax.add_patch(rect)

            # Draw operation blocks on top (multiply location by block_size for display)
            for i, location in enumerate(self.block_locations):
                display_location = location * self.block_size
                rect = mpatches.Rectangle(
                    (display_location, 0), self.block_size, 1,
                    facecolor=colors['block'][i], edgecolor='black', linewidth=1.5,
                    zorder=10
                )
                ax.add_patch(rect)

                # Add operation number label
                ax.text(display_location + self.block_size/2, 0.5, str(i),
                       ha='center', va='center', fontsize=8, fontweight='bold',
                       zorder=11)

        # Draw unused space at the end if any
        if self.num_instances > 1:
            all_locations = []
            for inst in self.instances:
                all_locations.extend(inst['block_locations'])
            if all_locations:
                last_block_end = (max(all_locations) + 1) * self.block_size
                if last_block_end < display_range:
                    rect = mpatches.Rectangle(
                        (last_block_end, 0), display_range - last_block_end, 1,
                        facecolor=colors['unused'], edgecolor='black', linewidth=0.5,
                        alpha=0.3
                    )
                    ax.add_patch(rect)
        else:
            if self.block_locations:
                last_block_end = (self.block_locations[-1] + 1) * self.block_size
                if last_block_end < display_range:
                    rect = mpatches.Rectangle(
                        (last_block_end, 0), display_range - last_block_end, 1,
                        facecolor=colors['unused'], edgecolor='black', linewidth=0.5,
                        alpha=0.3
                    )
                    ax.add_patch(rect)

        # Set up the plot
        ax.set_xlim(0, display_range)
        ax.set_ylim(0, 1)
        ax.set_xlabel('Byte Position (Block# × Block Size)', fontsize=12, fontweight='bold')
        ax.set_ylabel('')
        ax.set_yticks([])

        # Create title
        if title is None:
            if self.num_instances > 1:
                title = f'XDD Seek List Visualization - Multi-Instance Mode\n'
                title += f'Instances: {self.num_instances}, Ops per Instance: {self.num_ops}, Block Size: {self.block_size}\n'
            else:
                title = f'XDD Seek List Visualization\n'
                title += f'Ops: {self.num_ops}, Block Size: {self.block_size}, '
                title += f'Start Offset: {self.start_offset}, Seek Range: {self.seek_range}\n'

            if self.stagger:
                if self.stagger_value:
                    title += f'Stagger: ON (stride={self.stagger_value}), '
                else:
                    title += f'Stagger: ON (auto), '
            else:
                title += 'Stagger: OFF, '

            if self.interleave:
                title += f'Interleave: ON (value={self.interleave_value})'
            else:
                title += 'Interleave: OFF'

        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

        # Create custom legend
        legend_elements = []

        if self.num_instances > 1:
            # Multi-instance mode: show instances
            for i in range(self.num_instances):
                legend_elements.append(mpatches.Patch(facecolor=colors['instance'][i],
                                                     edgecolor='black', label=f'Instance {i}'))
        else:
            # Single-instance mode: show operation blocks
            legend_elements.append(mpatches.Patch(facecolor=colors['block'][0],
                                                 edgecolor='black', label='Operation Blocks'))

        # Check for gaps across all instances or single instance
        has_interleave_offset = False
        has_interleave_gap = False
        has_stagger_gap = False

        if self.num_instances > 1:
            for inst in self.instances:
                if any(g['type'] == 'interleave_offset' for g in inst['gap_info']):
                    has_interleave_offset = True
                if any(g['type'] == 'interleave' for g in inst['gap_info']):
                    has_interleave_gap = True
                if any(g['type'] == 'stagger' for g in inst['gap_info']):
                    has_stagger_gap = True
        else:
            has_interleave_offset = any(g['type'] == 'interleave_offset' for g in self.gap_info)
            has_interleave_gap = any(g['type'] == 'interleave' for g in self.gap_info)
            has_stagger_gap = any(g['type'] == 'stagger' for g in self.gap_info)

        if has_interleave_offset:
            legend_elements.append(mpatches.Patch(facecolor=colors['interleave_offset'],
                                                 edgecolor='black', label='Interleave Initial Offset'))

        if has_interleave_gap:
            legend_elements.append(mpatches.Patch(facecolor=colors['interleave_gap'],
                                                 edgecolor='black', label='Interleave Gap'))

        if has_stagger_gap:
            legend_elements.append(mpatches.Patch(facecolor=colors['stagger_gap'],
                                                 edgecolor='black', label='Stagger Gap'))

        legend_elements.append(mpatches.Patch(facecolor=colors['unused'],
                                             edgecolor='black', alpha=0.3, label='Unused Space'))

        ax.legend(handles=legend_elements, loc='upper right', fontsize=10)

        # Add grid for easier reading
        ax.grid(True, axis='x', alpha=0.3, linestyle='--')

        plt.tight_layout()
        return fig, ax

    def print_summary(self):
        """Print a text summary of the block locations."""
        if self.num_instances <= 1 and not self.block_locations:
            self.calculate_block_locations()
        elif self.num_instances > 1 and not self.instances:
            self.calculate_block_locations()

        print("\n" + "="*70)
        if self.num_instances > 1:
            print("XDD SEEK LIST BLOCK LOCATIONS - MULTI-INSTANCE MODE")
        else:
            print("XDD SEEK LIST BLOCK LOCATIONS")
        print("="*70)

        if self.num_instances > 1:
            print(f"Number of Instances: {self.num_instances}")
            print(f"Operations per Instance: {self.num_ops}")
        else:
            print(f"Number of Operations: {self.num_ops}")

        print(f"Block Size: {self.block_size}")

        if self.num_instances <= 1:
            print(f"Start Offset: {self.start_offset}")

        print(f"Seek Range: {self.seek_range}")
        print(f"Stagger: {'ON' if self.stagger else 'OFF'}", end='')
        if self.stagger and self.stagger_value:
            print(f" (stride={self.stagger_value})")
        elif self.stagger:
            print(" (auto-calculated)")
        else:
            print()
        print(f"Interleave: {'ON' if self.interleave else 'OFF'}", end='')
        if self.interleave:
            print(f" (value={self.interleave_value})")
        else:
            print()

        if self.num_instances > 1:
            # Multi-instance mode
            print("\n" + "="*70)
            print("INSTANCE START OFFSETS (for proper interleaving)")
            print("="*70)
            for inst in self.instances:
                inst_id = inst['instance_id']
                start_off = inst['start_offset']
                byte_start = start_off * self.block_size
                print(f"Instance {inst_id}: Block Offset = {start_off}, Byte Offset = {byte_start}")

            for inst in self.instances:
                inst_id = inst['instance_id']
                block_locations = inst['block_locations']
                gap_info = inst['gap_info']

                print("\n" + "="*70)
                print(f"INSTANCE {inst_id} - BLOCK LOCATIONS")
                print("="*70)
                print(f"Start Offset: {inst['start_offset']} (byte offset: {inst['start_offset'] * self.block_size})")
                print("-"*70)
                print(f"{'Op#':<6} {'Block#':<12} {'Byte Start':<15} {'Byte End':<15}")
                print("-"*70)

                for i, location in enumerate(block_locations):
                    byte_start = location * self.block_size
                    byte_end = (location + 1) * self.block_size
                    print(f"{i:<6} {location:<12} {byte_start:<15} {byte_end:<15}")

                if gap_info:
                    print("\n" + "-"*70)
                    print(f"INSTANCE {inst_id} - GAP ANALYSIS")
                    print("-"*70)
                    for gap in gap_info:
                        size = gap['end'] - gap['start']
                        print(f"{gap['description']}: bytes {gap['start']} to {gap['end']} (size: {size})")
        else:
            # Single-instance mode
            print("-"*70)
            print(f"{'Op#':<6} {'Block#':<12} {'Byte Start':<15} {'Byte End':<15}")
            print("-"*70)

            for i, location in enumerate(self.block_locations):
                byte_start = location * self.block_size
                byte_end = (location + 1) * self.block_size
                print(f"{i:<6} {location:<12} {byte_start:<15} {byte_end:<15}")

            if self.gap_info:
                print("\n" + "-"*70)
                print("GAP ANALYSIS")
                print("-"*70)
                for gap in self.gap_info:
                    size = gap['end'] - gap['start']
                    print(f"{gap['description']}: blocks {gap['start']} to {gap['end']} (size: {size})")

        print("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Visualize XDD seek list block locations with stagger and interleave options',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default sequential (no stagger, no interleave)
  %(prog)s -n 10

  # With stagger (auto-calculated gap)
  %(prog)s -n 10 --stagger

  # With stagger and specific stride
  %(prog)s -n 10 --stagger --stagger-value 5

  # With interleave
  %(prog)s -n 10 --interleave --interleave-value 3

  # With both stagger and interleave
  %(prog)s -n 10 --stagger --interleave --interleave-value 3

  # Multi-instance mode with interleave (shows how instances weave together)
  %(prog)s -n 10 --interleave --interleave-value 3 --instances 3

  # Complex example with all parameters
  %(prog)s -n 8 -b 2 -s 10 -r 200 --stagger --stagger-value 10 --interleave --interleave-value 4

  # Multi-instance with block size
  %(prog)s -n 5 -b 4096 --interleave --interleave-value 4 --instances 4
        """
    )

    parser.add_argument('-n', '--num-ops', type=int, default=1,
                       help='Number of operations')
    parser.add_argument('-b', '--block-size', type=int, default=1,
                       help='Block size (default: 1)')
    parser.add_argument('-s', '--start-offset', type=int, default=0,
                       help='Start offset (default: 0)')
    parser.add_argument('-r', '--seek-range', type=int, default=None,
                       help='Seek range (default: auto-calculated)')
    parser.add_argument('--stagger', action='store_true',
                       help='Enable stagger mode')
    parser.add_argument('--stagger-value', type=int, default=None,
                       help='Stagger stride value (if not set, gap is auto-calculated)')
    parser.add_argument('--interleave', action='store_true',
                       help='Enable interleave mode')
    parser.add_argument('--interleave-value', type=int, default=1,
                       help='Interleave multiplier value (default: 1)')
    parser.add_argument('--instances', type=int, default=1,
                       help='Number of process instances to visualize (default: 1). '
                            'When > 1, shows how multiple instances interleave with proper start offsets.')
    parser.add_argument('--no-display', action='store_true',
                       help='Skip displaying the plot (print summary only)')
    parser.add_argument('-o', '--output', type=str, default=None,
                       help='Save plot to file instead of displaying')

    args = parser.parse_args()

    # Create visualizer
    visualizer = SeekListVisualizer(
        num_ops=args.num_ops,
        block_size=args.block_size,
        start_offset=args.start_offset,
        seek_range=args.seek_range,
        stagger=args.stagger,
        stagger_value=args.stagger_value,
        interleave=args.interleave,
        interleave_value=args.interleave_value,
        num_instances=args.instances
    )

    # Print summary
    visualizer.print_summary()

    # Create and display/save visualization
    if not args.no_display:
        fig, ax = visualizer.visualize()

        if args.output:
            plt.savefig(args.output, dpi=300, bbox_inches='tight')
            print(f"Plot saved to: {args.output}")
        else:
            plt.show()


if __name__ == '__main__':
    main()
