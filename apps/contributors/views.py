from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce
from .models import Contributor, ContributorCategory, Contribution
from .forms import ContributorForm, ContributionForm

@login_required
def contributor_dashboard(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in ContributorCategory.values
    ]

    contributors = Contributor.objects.filter(user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            contributors = contributors.exclude(category__in=selected_categories)
        else:
            contributors = contributors.filter(category__in=selected_categories)

    total_contributors = contributors.count()
    
    # Total contributions across all contributors
    total_contribution_amount = contributors.aggregate(
        total=Coalesce(Sum("contributions__amount"), Value(0, output_field=DecimalField()))
    )["total"]
    
    # Data for the chart: Top contributors
    top_contributors = contributors.annotate(
        total_amount=Coalesce(
            Sum("contributions__amount"),
            Value(0, output_field=DecimalField()),
        )
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
        ).filter(
            Q() if not selected_categories else (
                ~Q(contributor__category__in=selected_categories)
                if filter_type == "exclude"
                else Q(contributor__category__in=selected_categories)
            )
        ).select_related('contributor').order_by('-date', '-created_at')[:10],
        "selected_categories": selected_categories,
        "category_choices": ContributorCategory.choices,
        "filter_type": filter_type,
    }
    return render(request, 'contributors/dashboard.html', context)

@login_required
def contributor_list(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in ContributorCategory.values
    ]

    contributors_base_qs = Contributor.objects.filter(user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            contributors_base_qs = contributors_base_qs.exclude(category__in=selected_categories)
        else:
            contributors_base_qs = contributors_base_qs.filter(category__in=selected_categories)

    contributors = contributors_base_qs.annotate(
        total_amount=Coalesce(
            Sum("contributions__amount"),
            Value(0, output_field=DecimalField()),
        )
    )

    total_contributors = contributors_base_qs.count()
    total_contribution_amount = contributors_base_qs.aggregate(
        total=Coalesce(Sum("contributions__amount"), Value(0, output_field=DecimalField()))
    )["total"]
    avg_contribution = (
        total_contribution_amount / total_contributors if total_contributors > 0 else 0
    )

    context = {
        "contributors": contributors,
        "total_contributors": total_contributors,
        "total_contribution_amount": total_contribution_amount,
        "avg_contribution": avg_contribution,
        "selected_categories": selected_categories,
        "category_choices": ContributorCategory.choices,
        "filter_type": filter_type,
    }
    return render(request, 'contributors/contributor_list.html', context)

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
