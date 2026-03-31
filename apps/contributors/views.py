from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from .models import Contributor, Contribution
from .forms import ContributorForm, ContributionForm

@login_required
def contributor_dashboard(request):
    contributors = Contributor.objects.filter(user=request.user)
    total_contributors = contributors.count()
    
    # Total contributions across all contributors
    total_contribution_amount = Contribution.objects.filter(
        contributor__user=request.user
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Data for the chart: Top contributors
    top_contributors = contributors.annotate(
        total_amount=Sum('contributions__amount')
    ).order_by('-total_amount')[:10]
    
    chart_labels = [c.name for c in top_contributors if c.total_amount]
    chart_data = [float(c.total_amount) for c in top_contributors if c.total_amount]

    avg_contribution = total_contribution_amount / total_contributors if total_contributors > 0 else 0

    context = {
        'total_contributors': total_contributors,
        'total_contribution_amount': total_contribution_amount,
        'avg_contribution': avg_contribution,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'recent_contributions': Contribution.objects.filter(
            contributor__user=request.user
        ).select_related('contributor').order_by('-date')[:10],
    }
    return render(request, 'contributors/dashboard.html', context)

@login_required
def contributor_list(request):
    contributors = Contributor.objects.filter(user=request.user).annotate(
        total_amount=Sum('contributions__amount')
    )
    return render(request, 'contributors/contributor_list.html', {'contributors': contributors})

@login_required
def contributor_create(request):
    if request.method == 'POST':
        form = ContributorForm(request.POST)
        if form.is_valid():
            contributor = form.save(commit=False)
            contributor.user = request.user
            contributor.save()
            return redirect('contributor_list')
    else:
        form = ContributorForm()
    return render(request, 'contributors/contributor_form.html', {'form': form, 'title': 'Add Contributor'})

@login_required
def contributor_update(request, pk):
    contributor = get_object_or_404(Contributor, pk=pk, user=request.user)
    if request.method == 'POST':
        form = ContributorForm(request.POST, instance=contributor)
        if form.is_valid():
            form.save()
            return redirect('contributor_list')
    else:
        form = ContributorForm(instance=contributor)
    return render(request, 'contributors/contributor_form.html', {'form': form, 'title': 'Edit Contributor'})

@login_required
def contributor_delete(request, pk):
    contributor = get_object_or_404(Contributor, pk=pk, user=request.user)
    if request.method == 'POST':
        contributor.delete()
        return redirect('contributor_list')
    return render(request, 'contributors/contributor_confirm_delete.html', {'contributor': contributor})

@login_required
def contributor_detail(request, pk):
    contributor = get_object_or_404(Contributor, pk=pk, user=request.user)
    contributions = contributor.contributions.all().order_by('-date')
    
    total_amount = contributions.aggregate(Sum('amount'))['amount__sum'] or 0
    total_count = contributions.count()
    avg_amount = total_amount / total_count if total_count > 0 else 0

    if request.method == 'POST':
        form = ContributionForm(request.POST)
        if form.is_valid():
            contribution = form.save(commit=False)
            contribution.contributor = contributor
            contribution.save()
            return redirect('contributor_detail', pk=pk)
    else:
        form = ContributionForm()

    context = {
        'contributor': contributor,
        'contributions': contributions,
        'total_amount': total_amount,
        'total_count': total_count,
        'avg_amount': avg_amount,
        'form': form,
    }
    return render(request, 'contributors/contributor_detail.html', context)

@login_required
def contribution_update(request, pk):
    contribution = get_object_or_404(Contribution, pk=pk, contributor__user=request.user)
    contributor = contribution.contributor
    if request.method == 'POST':
        form = ContributionForm(request.POST, instance=contribution)
        if form.is_valid():
            form.save()
            return redirect('contributor_detail', pk=contributor.pk)
    else:
        form = ContributionForm(instance=contribution)
    return render(request, 'contributors/contribution_form.html', {
        'form': form, 
        'title': 'Edit Record', 
        'contributor': contributor
    })

@login_required
def contribution_delete(request, pk):
    contribution = get_object_or_404(Contribution, pk=pk, contributor__user=request.user)
    contributor_pk = contribution.contributor.pk
    contribution.delete()
    return redirect('contributor_detail', pk=contributor_pk)
